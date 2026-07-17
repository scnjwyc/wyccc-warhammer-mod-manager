# Workshop Cover Upload Design

## Goal

Make every Workshop publish or update upload a standard MOD payload consisting
of exactly the selected `.pack` file and a sibling, same-stem `.png` cover.
The cover must not exceed 1 MiB and is also used as the Steam preview image.

## Current Problem

Publishing currently stages only the Pack into a temporary content directory.
It accepts a separately chosen PNG/JPEG path as Steam's preview image, so the
cover is not part of the downloaded Workshop MOD and can have a different name
or directory.

## Chosen Design

- The canonical cover for `example.pack` is `example.png` in the same
  directory.
- The backend derives that path from the publishable Pack. It does not trust an
  arbitrary path supplied by the browser.
- The backend rejects missing covers and covers larger than `1_024 * 1_024`
  bytes before any Steamworks call.
- The temporary content directory contains `example.pack` and `example.png`.
  The staged PNG is also passed to Steamworks as `previewPath`.
- The publish dialog displays the required cover path and the naming/size rule;
  it no longer offers a file browser for arbitrary preview files.

## Error Handling

Both new uploads and updates use the same validation. A missing or oversized
cover returns a clear API error and leaves the current Workshop association
unchanged. The temporary upload directory is still automatically removed after
each attempt.

## Validation

- API tests prove that staged content has both same-stem files, the staged PNG
  is the Steam preview, and missing/oversized covers are rejected.
- Component tests prove that the derived `.png` path is shown, cannot be edited,
  and is not submitted as an arbitrary field.
- Existing Steamworks bridge tests continue to prove that the resulting content
  and preview paths are forwarded to the native bridge.
