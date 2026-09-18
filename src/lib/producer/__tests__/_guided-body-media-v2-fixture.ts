/** Pure TEST transport metadata only; these values do not authenticate media or admission. */
import { BODY_MEDIA_PROFILE, BODY_MEDIA_REFERENCES } from "../contracts/guided-body-media-v1";
import { BODY_SOURCE_COLOR_REPLAY_SCOPE } from "../contracts/guided-body-source-color-replay-v2";

export const BODY_MEDIA_TEST_HASH = "a".repeat(64);
export const BODY_MEDIA_TEST_EXECUTION = "00000000-0000-4000-8000-000000000001";
export const BODY_MEDIA_TEST_ATTEMPT = "00000000-0000-4000-8000-000000000002";

/** Shape-only runtime: no real tool/socket is read by this fixture. */
export function bodyMediaTestRuntime(root: string) {
  const sha = BODY_MEDIA_TEST_HASH;
  return { dockerPath: `${root}/TEST-docker`, dockerSha256: sha, dockerSocketPath: `${root}/TEST-docker.sock`,
    dockerSocketDevice: "1", dockerSocketInode: "2", imageId: `sha256:${sha}`, userId: "501:20",
    imageApprovalPath: `${root}/TEST-image.json`, imageApprovalSha256: sha, runtimeRepoRoot: root };
}

/** Original opening references are distinct from this future body's execution UUID. */
export function bodyMediaTestReplay(root: string) {
  const sha = BODY_MEDIA_TEST_HASH, execution = `${root}/executions/${BODY_MEDIA_TEST_EXECUTION}`;
  return { schemaVersion: 2 as const, kind: "guided-body-source-color-replay-references" as const,
    scope: BODY_SOURCE_COLOR_REPLAY_SCOPE,
    opening: { selectionHash: sha, claimHash: sha, cleanupHash: sha, executionId: BODY_MEDIA_TEST_EXECUTION,
      inputSha256: sha, executionInputHash: sha, mediaResultSha256: sha, receiptHash: sha },
    sourceColorHash: sha, input: { path: `${execution}/source-color/input.json`, sha256: sha, sizeBytes: 1 },
    reservationArchive: { path: `${execution}/cleanup-attempts/${BODY_MEDIA_TEST_ATTEMPT}/reservation.json`, sha256: sha, sizeBytes: 1 },
    executable: false as const, bodyApproved: false as const, deliveryApproved: false as const };
}

/** Legacy nine-field document; callers can prove the historical parser has not widened. */
export function bodyMediaTestV1(root = "/private/tmp/TEST-body-media-metadata") {
  return { schemaVersion: 1 as const, kind: "guided-body-media-input" as const, scope: "private-body-candidate-not-approval" as const,
    profile: BODY_MEDIA_PROFILE, requestId: "00000000-0000-4000-8000-000000000003", executionId: BODY_MEDIA_TEST_ATTEMPT,
    references: Object.fromEntries(BODY_MEDIA_REFERENCES.map(name => [name, { path: `${root}/${name}.json`, sha256: BODY_MEDIA_TEST_HASH }])),
    runtime: bodyMediaTestRuntime(root), selectedGraphicOrders: [0, 1] };
}

/** Exactly one additional top-level field; the original seven-reference map remains unchanged. */
export function bodyMediaTestV2(root = "/private/tmp/TEST-body-media-metadata") {
  return { ...bodyMediaTestV1(root), schemaVersion: 2 as const, sourceColorReplay: bodyMediaTestReplay(root) };
}

/** Detached omission cases for every closed-record required key. */
export function bodyMediaOmissions(row: object): Record<string, unknown>[] {
  return Object.keys(row).map(key => {
    const next: Record<string, unknown> = { ...row }; delete next[key]; return next;
  });
}

/** Exercise every unchanged original reference role with missing/extra nested keys. */
export function bodyMediaReferenceChanges(row: ReturnType<typeof bodyMediaTestV1> | ReturnType<typeof bodyMediaTestV2>) {
  return BODY_MEDIA_REFERENCES.flatMap(name => {
    const reference = row.references[name], changes = [...bodyMediaOmissions(reference), { ...reference, sizeBytes: 1 }];
    return changes.map(value => ({ ...row, references: { ...row.references, [name]: value } }));
  });
}
