const issueCode = {
  type: "string", minLength: 2, maxLength: 64,
  pattern: "^[A-Z0-9][A-Z0-9_-]+$",
} as const;

export const PRODUCER_REVISION_JSON_SCHEMA = {
  type: "object",
  additionalProperties: false,
  properties: {
    schemaVersion: { type: "integer", const: 1 },
    changedPlan: { type: "boolean" },
    addressedIssueCodes: {
      type: "array", maxItems: 50, uniqueItems: true, items: issueCode,
    },
    deferredIssueCodes: {
      type: "array", maxItems: 50, uniqueItems: true, items: issueCode,
    },
    summary: { type: "string", minLength: 1, maxLength: 2000 },
  },
  required: [
    "schemaVersion", "changedPlan", "addressedIssueCodes",
    "deferredIssueCodes", "summary",
  ],
} as const;

export function producerRevisionJsonSchema(issueCodes: string[]): Record<string, unknown> {
  const allowedIssueCode = { ...issueCode, enum: [...issueCodes] };
  return {
    ...PRODUCER_REVISION_JSON_SCHEMA,
    properties: {
      ...PRODUCER_REVISION_JSON_SCHEMA.properties,
      addressedIssueCodes: {
        ...PRODUCER_REVISION_JSON_SCHEMA.properties.addressedIssueCodes,
        items: allowedIssueCode,
        description: "Material issue codes addressed by the plan mutation. Copy only supplied codes verbatim.",
      },
      deferredIssueCodes: {
        ...PRODUCER_REVISION_JSON_SCHEMA.properties.deferredIssueCodes,
        items: allowedIssueCode,
        description: "Material issue codes that cannot be repaired. Copy only supplied codes verbatim.",
      },
    },
  };
}
