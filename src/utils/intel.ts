/**
 * Backend-intel fetch decisions (evidence + alerts for one call).
 *
 * Pure logic with zero dependencies, intentionally written without
 * TypeScript-only syntax so the regression harness can execute this exact
 * file with plain Node: `node harness_intel.js` (see Temp scratch dir).
 *
 * Policy (mirrors CallContext.refreshBackendIntel):
 * - Empty call id: never fetch.
 * - Live subscription path (allowEnded=false): only active calls, so one
 *   call's intel can never leak into another call's state.
 * - Explicit ended-call path (allowEnded=true): a selected ENDED/history
 *   call may refetch its own B4 records by authoritative id. B4 serves
 *   evidence/alerts for terminated calls; the UI purges caches on endCall,
 *   so this is the only way history evidence is reachable.
 * - Bounded: one in-flight fetch per call; at most one refresh per
 *   INTEL_THROTTLE_MS per call unless forced. Failures never fabricate.
 *
 * @param {object} args
 * @param {string} args.callId
 * @param {boolean} args.isActive
 * @param {boolean} args.allowEnded
 * @param {number} args.nowMs
 * @param {number|undefined} args.lastFetchMs
 * @param {boolean} args.inflight
 * @param {boolean} args.force
 * @returns {{decision: 'fetch'|'skip', reason: string}}
 */
export const INTEL_THROTTLE_MS = 10000;

/**
 * Arguments for resolveIntelFetch, mirroring the object built by
 * CallContext.refreshBackendIntel (same field names and value shapes).
 */
export interface IntelFetchArgs {
  callId: string;
  isActive: boolean;
  allowEnded: boolean;
  nowMs: number;
  lastFetchMs: number | undefined;
  inflight: boolean;
  force: boolean;
}

export function resolveIntelFetch(args: IntelFetchArgs) {
  const callId = args.callId;
  const isActive = args.isActive === true;
  const allowEnded = args.allowEnded === true;
  const force = args.force === true;
  if (typeof callId !== 'string' || callId.length === 0) {
    return { decision: 'skip', reason: 'empty-call-id' };
  }
  if (!isActive && !allowEnded) {
    return { decision: 'skip', reason: 'not-active' };
  }
  if (args.inflight === true) {
    return { decision: 'skip', reason: 'inflight' };
  }
  if (force !== true) {
    const last = typeof args.lastFetchMs === 'number' ? args.lastFetchMs : 0;
    if (args.nowMs - last < INTEL_THROTTLE_MS) {
      return { decision: 'skip', reason: 'throttled' };
    }
  }
  return { decision: 'fetch', reason: isActive ? 'active' : 'ended-explicit' };
}
