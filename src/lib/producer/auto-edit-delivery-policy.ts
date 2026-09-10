export const AUTO_EDIT_DELIVERY_POLICIES = [
  "palmier-hybrid",
  "mp4-only",
] as const;

export type AutoEditDeliveryPolicy =
  (typeof AUTO_EDIT_DELIVERY_POLICIES)[number];

export const DEFAULT_AUTO_EDIT_DELIVERY_POLICY: AutoEditDeliveryPolicy =
  "palmier-hybrid";

/** Parse one closed production delivery policy; omission preserves legacy hybrid behavior. */
export function parseAutoEditDeliveryPolicy(
  value: unknown,
): AutoEditDeliveryPolicy {
  if (value === undefined) return DEFAULT_AUTO_EDIT_DELIVERY_POLICY;
  if (AUTO_EDIT_DELIVERY_POLICIES.includes(value as AutoEditDeliveryPolicy)) {
    return value as AutoEditDeliveryPolicy;
  }
  throw new Error(
    `deliveryPolicy must be one of: ${AUTO_EDIT_DELIVERY_POLICIES.join(", ")}`,
  );
}

/** Resolve old durable journals as their historical Palmier-hybrid default. */
export function resolvedAutoEditDeliveryPolicy(
  ctx: { deliveryPolicy?: unknown },
): AutoEditDeliveryPolicy {
  return parseAutoEditDeliveryPolicy(ctx.deliveryPolicy);
}

export function autoEditWorkbench(
  ctx: { deliveryPolicy?: unknown },
): "Palmier" | "MP4" {
  return resolvedAutoEditDeliveryPolicy(ctx) === "mp4-only" ? "MP4" : "Palmier";
}
