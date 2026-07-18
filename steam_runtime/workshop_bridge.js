"use strict";

const fs = require("fs");
const path = require("path");

const RESULT_PREFIX = "WMM_WORKSHOP_RESULT=";
const QUERY_CHUNK_SIZE = 100;
const DEPENDENCY_QUERY_CONCURRENCY = 16;
const WORKSHOP_ITEM_INSTALLED = 4;
const WORKSHOP_ITEM_DOWNLOAD_BUSY = 8 | 16 | 32;
const FORCE_UPDATE_TIMEOUT_MS = 10 * 60 * 1000;
const FORCE_UPDATE_POLL_INTERVAL_MS = 100;

const writeResultAndExit = (payload, exitCode) => {
  const line = `${RESULT_PREFIX}${JSON.stringify(payload)}\n`;
  process.stdout.write(line, () => process.exit(exitCode));
};

const readRequest = async () => {
  const chunks = [];
  for await (const chunk of process.stdin) chunks.push(chunk);
  return JSON.parse(Buffer.concat(chunks).toString("utf8"));
};

const wait = milliseconds => new Promise(resolve => setTimeout(resolve, milliseconds));

const directorySize = root => {
  if (!root || !fs.existsSync(root)) return 0n;
  const pending = [root];
  let total = 0n;
  while (pending.length) {
    const directory = pending.pop();
    let entries;
    try {
      entries = fs.readdirSync(directory, { withFileTypes: true });
    } catch {
      return 0n;
    }
    for (const entry of entries) {
      const itemPath = path.join(directory, entry.name);
      if (entry.isDirectory()) {
        pending.push(itemPath);
      } else if (entry.isFile()) {
        try {
          total += BigInt(fs.statSync(itemPath).size);
        } catch {
          return 0n;
        }
      }
    }
  }
  return total;
};

const workshopDownloadStatus = (workshop, itemId) => {
  const state = Number(workshop.state(itemId) || 0);
  const installInfo = workshop.installInfo(itemId);
  const downloadInfo = workshop.downloadInfo(itemId);
  const installPath = String(installInfo?.folder || "");
  const expectedSize = BigInt(installInfo?.sizeOnDisk || 0);
  const actualSize = directorySize(installPath);
  return {
    state,
    installPath,
    expectedSize,
    actualSize,
    downloadedBytes: BigInt(downloadInfo?.current || 0),
    totalBytes: BigInt(downloadInfo?.total || 0),
  };
};

const waitForWorkshopDownload = async (workshop, itemId) => {
  const startedAt = Date.now();
  let status;
  while (Date.now() - startedAt <= FORCE_UPDATE_TIMEOUT_MS) {
    status = workshopDownloadStatus(workshop, itemId);
    const installed = (status.state & WORKSHOP_ITEM_INSTALLED) !== 0;
    const busy = (status.state & WORKSHOP_ITEM_DOWNLOAD_BUSY) !== 0;
    const diskComplete = Boolean(status.installPath)
      && fs.existsSync(status.installPath)
      && (status.expectedSize === 0n || status.actualSize >= status.expectedSize);
    if (installed && !busy && diskComplete) {
      return {
        completed: true,
        state: status.state,
        install_path: status.installPath,
        size_on_disk: status.expectedSize.toString(),
        actual_size_on_disk: status.actualSize.toString(),
        downloaded_bytes: status.downloadedBytes.toString(),
        total_bytes: status.totalBytes.toString(),
      };
    }
    await wait(FORCE_UPDATE_POLL_INTERVAL_MS);
  }
  throw new Error(
    `Timed out waiting for Workshop item ${itemId.toString()} to finish downloading `
    + `(state=${status?.state ?? 0}, downloaded=${status?.downloadedBytes ?? 0}/${status?.totalBytes ?? 0})`,
  );
};

const serializeItem = item => ({
  workshop_id: item.publishedFileId.toString(),
  title: String(item.title || ""),
  description: String(item.description || ""),
  creator_id: item.owner && item.owner.steamId64 ? item.owner.steamId64.toString() : "",
  preview_url: String(item.previewUrl || ""),
  created_at: Number(item.timeCreated || 0) * 1000,
  updated_at: Number(item.timeUpdated || 0) * 1000,
  tags: Array.isArray(item.tags) ? item.tags.map(String) : [],
});

const addQueryResult = (target, queryResult) => {
  for (const item of queryResult?.items || []) {
    if (!item) continue;
    const serialized = serializeItem(item);
    target[serialized.workshop_id] = serialized;
  }
};

const ensureWorkshopSubscription = async (workshop, itemId) => {
  const workshopId = itemId.toString();
  const subscribedIds = new Set(
    (workshop.getSubscribedItems() || []).map(value => value.toString()),
  );
  if (subscribedIds.has(workshopId)) return false;
  await workshop.subscribe(itemId);
  return true;
};

const queryLanguage = async (client, ids, language, warnings) => {
  const items = {};
  for (let start = 0; start < ids.length; start += QUERY_CHUNK_SIZE) {
    const chunk = ids.slice(start, start + QUERY_CHUNK_SIZE);
    try {
      const result = await client.workshop.getItems(chunk, {
        language,
        includeLongDescription: true,
      });
      addQueryResult(items, result);
    } catch (batchError) {
      warnings.push(`${language} batch ${start}: ${String(batchError)}`);
      for (const id of chunk) {
        try {
          const result = await client.workshop.getItems([id], {
            language,
            includeLongDescription: true,
          });
          addQueryResult(items, result);
        } catch (itemError) {
          warnings.push(`${language} item ${id.toString()}: ${String(itemError)}`);
        }
      }
    }
  }
  return items;
};

const forEachConcurrent = async (values, concurrency, worker) => {
  let nextIndex = 0;
  const runners = Array.from(
    { length: Math.min(Math.max(1, concurrency), values.length) },
    async () => {
      while (nextIndex < values.length) {
        const index = nextIndex;
        nextIndex += 1;
        await worker(values[index], index);
      }
    },
  );
  await Promise.all(runners);
};

const main = async () => {
  const request = await readRequest();
  const appId = Number(request?.appId || 0);
  const operation = String(request?.operation || "query");
  if (!Number.isInteger(appId) || appId <= 0) throw new Error("Invalid Steam App ID");

  const steamworks = operation === "query_dependencies"
    ? require("./steamworks_dependencies")
    : require("./steamworks");
  const client = steamworks.init(appId);
  if (operation === "get_current_user") {
    const steamId = client.localplayer.getSteamId()?.steamId64?.toString?.() || "";
    if (!/^\d+$/.test(steamId)) throw new Error("Current Steam user is unavailable");
    writeResultAndExit({
      ok: true,
      result: {
        steam_id: steamId,
        name: String(client.localplayer.getName() || ""),
      },
    }, 0);
    return;
  }
  if (operation === "query_subscriptions") {
    const ids = [...new Set((request?.ids || []).map(String))]
      .filter(value => /^\d+$/.test(value));
    const language = String(request?.language || "english");
    if (!ids.length) throw new Error("No valid Workshop IDs were supplied");
    const subscribedIds = new Set(
      (client.workshop.getSubscribedItems() || []).map(value => value.toString()),
    );
    const warnings = [];
    const titles = await queryLanguage(
      client,
      ids.map(value => BigInt(value)),
      language,
      warnings,
    );
    const subscriptions = Object.fromEntries(ids.map(id => [id, {
      workshop_id: id,
      title: String(titles[id]?.title || ""),
      subscribed: subscribedIds.has(id),
    }]));
    writeResultAndExit({ ok: true, subscriptions, warnings }, 0);
    return;
  }
  if (operation === "subscribe_many") {
    const ids = [...new Set((request?.ids || []).map(String))]
      .filter(value => /^\d+$/.test(value));
    if (!ids.length) throw new Error("No valid Workshop IDs were supplied");
    const existing = new Set(
      (client.workshop.getSubscribedItems() || []).map(value => value.toString()),
    );
    const subscribed = [];
    const alreadySubscribed = [];
    const failed = [];
    for (const id of ids) {
      if (existing.has(id)) {
        alreadySubscribed.push(id);
        continue;
      }
      try {
        await client.workshop.subscribe(BigInt(id));
        subscribed.push(id);
      } catch (error) {
        failed.push({ workshop_id: id, error: String(error) });
      }
    }
    writeResultAndExit({
      ok: true,
      result: {
        operation,
        subscribed,
        already_subscribed: alreadySubscribed,
        failed,
        accepted: true,
      },
    }, 0);
    return;
  }
  if (operation === "publish_item") {
    const requestedId = String(request?.id || "");
    if (requestedId && !/^\d+$/.test(requestedId)) throw new Error("Invalid Workshop ID");
    const contentPath = String(request?.contentPath || "");
    const previewPath = String(request?.previewPath || "");
    const title = String(request?.title || "").trim();
    const description = String(request?.description || "");
    const changeNote = String(request?.changeNote || "");
    const visibility = Number(request?.visibility ?? 0);
    const language = String(request?.language || "english").trim();
    const tags = [...new Set((request?.tags || []).map(String).filter(Boolean))];
    if (!contentPath || !fs.statSync(contentPath).isDirectory()) throw new Error("Upload content folder is missing");
    if (!previewPath || !fs.statSync(previewPath).isFile()) throw new Error("Workshop preview image is missing");
    if (!title) throw new Error("Workshop title is required");
    if (!Number.isInteger(visibility) || visibility < 0 || visibility > 3) throw new Error("Invalid visibility");
    if (!/^[a-z]+$/.test(language)) throw new Error("Invalid Workshop language");
    if (
      typeof client.workshop.supportsUpdateLanguage !== "function"
      || !client.workshop.supportsUpdateLanguage()
    ) {
      throw new Error("The bundled Steamworks bridge does not support localized Workshop updates");
    }

    const localPlayer = client.localplayer.getSteamId();
    const ownerId = localPlayer.steamId64.toString();
    const ownerName = String(client.localplayer.getName() || "");
    let itemId = requestedId ? BigInt(requestedId) : null;
    let created = false;
    let needsToAcceptAgreement = false;
    if (itemId) {
      const details = await client.workshop.getItems([itemId], { includeLongDescription: false });
      const item = (details?.items || []).find(Boolean);
      if (!item) throw new Error(`Workshop item ${requestedId} was not found`);
      const itemOwnerId = item.owner?.steamId64?.toString?.() || "";
      if (itemOwnerId !== ownerId) throw new Error("The current Steam account does not own this Workshop item");
    } else {
      const createdItem = await client.workshop.createItem(appId);
      itemId = createdItem.itemId;
      created = true;
      needsToAcceptAgreement = Boolean(createdItem.needsToAcceptAgreement);
    }

    try {
      const updatedItem = await client.workshop.updateItem(itemId, {
        title,
        description,
        changeNote,
        previewPath,
        contentPath,
        tags: tags.length ? tags : ["mod"],
        visibility,
        language,
      }, appId);
      needsToAcceptAgreement = needsToAcceptAgreement || Boolean(updatedItem.needsToAcceptAgreement);
    } catch (error) {
      if (created) {
        throw new Error(`Workshop item ${itemId.toString()} was created, but its content update failed: ${String(error)}`);
      }
      throw error;
    }
    const subscriptionAdded = await ensureWorkshopSubscription(client.workshop, itemId);
    writeResultAndExit({
      ok: true,
      result: {
        operation: created ? "upload" : "update",
        workshop_id: itemId.toString(),
        created,
        owner_id: ownerId,
        owner_name: ownerName,
        needs_to_accept_agreement: needsToAcceptAgreement,
        language,
        subscribed: true,
        subscription_added: subscriptionAdded,
      },
    }, 0);
    return;
  }
  if (operation === "subscribe" || operation === "unsubscribe" || operation === "force_update") {
    const workshopId = String(request?.id || "");
    if (!/^\d+$/.test(workshopId)) throw new Error("Invalid Workshop ID");
    const itemId = BigInt(workshopId);
    if (operation === "subscribe" || operation === "unsubscribe") {
      await client.workshop[operation](itemId);
      writeResultAndExit({
        ok: true,
        result: { operation, workshop_id: workshopId, accepted: true },
      }, 0);
      return;
    }
    const accepted = client.workshop.download(itemId, true);
    if (!accepted) throw new Error(`Steam rejected the update request for Workshop item ${workshopId}`);
    const completion = await waitForWorkshopDownload(client.workshop, itemId);
    writeResultAndExit({
      ok: true,
      result: {
        operation,
        workshop_id: workshopId,
        accepted: true,
        ...completion,
      },
    }, 0);
    return;
  }
  if (operation === "query_dependencies") {
    const ids = [...new Set((request?.ids || []).map(String))]
      .filter(value => /^\d+$/.test(value));
    const language = String(request?.language || "english");
    if (!ids.length) throw new Error("No valid Workshop IDs were supplied");
    if (typeof client.workshop.getItemDependencies !== "function") {
      throw new Error("The bundled Steamworks dependency-query module is incompatible");
    }
    const warnings = [];
    const dependencyIdsByItem = {};
    const dependencyFailures = [];
    const allDependencyIds = new Set();
    await forEachConcurrent(ids, DEPENDENCY_QUERY_CONCURRENCY, async id => {
      try {
        const dependencyIds = await client.workshop.getItemDependencies(BigInt(id));
        dependencyIdsByItem[id] = dependencyIds.map(value => value.toString());
        for (const dependencyId of dependencyIdsByItem[id]) allDependencyIds.add(dependencyId);
      } catch (error) {
        dependencyIdsByItem[id] = [];
        dependencyFailures.push(id);
        warnings.push(`dependencies item ${id}: ${String(error)}`);
      }
    });

    const titles = allDependencyIds.size
      ? await queryLanguage(
          client,
          [...allDependencyIds].map(value => BigInt(value)),
          language,
          warnings,
        )
      : {};
    const dependencies = {};
    for (const id of ids) {
      dependencies[id] = dependencyIdsByItem[id].map(dependencyId => ({
        workshop_id: dependencyId,
        title: String(titles[dependencyId]?.title || ""),
      }));
    }
    writeResultAndExit({ ok: true, dependencies, dependency_failures: dependencyFailures, warnings }, 0);
    return;
  }
  if (operation !== "query") throw new Error(`Unsupported operation: ${operation}`);

  const ids = [...new Set((request?.ids || []).map(String))]
    .filter(value => /^\d+$/.test(value))
    .map(value => BigInt(value));
  const languages = [...new Set((request?.languages || []).map(String))]
    .filter(value => /^[a-z]+$/.test(value));
  if (!ids.length) throw new Error("No valid Workshop IDs were supplied");
  if (!languages.length) throw new Error("No valid Steam languages were supplied");
  const warnings = [];
  const result = {};
  for (const language of languages) {
    result[language] = await queryLanguage(client, ids, language, warnings);
  }
  writeResultAndExit({ ok: true, languages: result, warnings }, 0);
};

main().catch(error => {
  writeResultAndExit({ ok: false, error: error?.stack || String(error) }, 1);
});
