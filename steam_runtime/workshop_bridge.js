"use strict";

const fs = require("fs");
const steamworks = require("./steamworks");

const RESULT_PREFIX = "WMM_WORKSHOP_RESULT=";
const QUERY_CHUNK_SIZE = 100;

const writeResultAndExit = (payload, exitCode) => {
  const line = `${RESULT_PREFIX}${JSON.stringify(payload)}\n`;
  process.stdout.write(line, () => process.exit(exitCode));
};

const readRequest = async () => {
  const chunks = [];
  for await (const chunk of process.stdin) chunks.push(chunk);
  return JSON.parse(Buffer.concat(chunks).toString("utf8"));
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

const main = async () => {
  const request = await readRequest();
  const appId = Number(request?.appId || 0);
  const operation = String(request?.operation || "query");
  if (!Number.isInteger(appId) || appId <= 0) throw new Error("Invalid Steam App ID");

  const client = steamworks.init(appId);
  if (operation === "publish_item") {
    const requestedId = String(request?.id || "");
    if (requestedId && !/^\d+$/.test(requestedId)) throw new Error("Invalid Workshop ID");
    const contentPath = String(request?.contentPath || "");
    const previewPath = String(request?.previewPath || "");
    const title = String(request?.title || "").trim();
    const description = String(request?.description || "");
    const changeNote = String(request?.changeNote || "");
    const visibility = Number(request?.visibility ?? 0);
    const tags = [...new Set((request?.tags || []).map(String).filter(Boolean))];
    if (!contentPath || !fs.statSync(contentPath).isDirectory()) throw new Error("Upload content folder is missing");
    if (!previewPath || !fs.statSync(previewPath).isFile()) throw new Error("Workshop preview image is missing");
    if (!title) throw new Error("Workshop title is required");
    if (!Number.isInteger(visibility) || visibility < 0 || visibility > 3) throw new Error("Invalid visibility");

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
      }, appId);
      needsToAcceptAgreement = needsToAcceptAgreement || Boolean(updatedItem.needsToAcceptAgreement);
    } catch (error) {
      if (created) {
        throw new Error(`Workshop item ${itemId.toString()} was created, but its content update failed: ${String(error)}`);
      }
      throw error;
    }
    writeResultAndExit({
      ok: true,
      result: {
        operation: created ? "upload" : "update",
        workshop_id: itemId.toString(),
        created,
        owner_id: ownerId,
        owner_name: ownerName,
        needs_to_accept_agreement: needsToAcceptAgreement,
      },
    }, 0);
    return;
  }
  if (operation === "unsubscribe" || operation === "force_update") {
    const workshopId = String(request?.id || "");
    if (!/^\d+$/.test(workshopId)) throw new Error("Invalid Workshop ID");
    const itemId = BigInt(workshopId);
    if (operation === "unsubscribe") {
      await client.workshop.unsubscribe(itemId);
      writeResultAndExit({
        ok: true,
        result: { operation, workshop_id: workshopId, accepted: true },
      }, 0);
      return;
    }
    const accepted = client.workshop.download(itemId, true);
    if (!accepted) throw new Error(`Steam rejected the update request for Workshop item ${workshopId}`);
    writeResultAndExit({
      ok: true,
      result: { operation, workshop_id: workshopId, accepted: true },
    }, 0);
    return;
  }
  if (operation === "query_dependencies") {
    const ids = [...new Set((request?.ids || []).map(String))]
      .filter(value => /^\d+$/.test(value));
    const language = String(request?.language || "english");
    if (!ids.length) throw new Error("No valid Workshop IDs were supplied");
    const warnings = [];
    const dependencyIdsByItem = {};
    const dependencyFailures = [];
    const allDependencyIds = new Set();
    await Promise.all(ids.map(async id => {
      try {
        const dependencyIds = await client.workshop.getItemDependencies(BigInt(id));
        dependencyIdsByItem[id] = dependencyIds.map(value => value.toString());
        for (const dependencyId of dependencyIdsByItem[id]) allDependencyIds.add(dependencyId);
      } catch (error) {
        dependencyIdsByItem[id] = [];
        dependencyFailures.push(id);
        warnings.push(`dependencies item ${id}: ${String(error)}`);
      }
    }));

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
