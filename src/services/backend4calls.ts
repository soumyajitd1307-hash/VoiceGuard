/**
 * Backend 4 call-lifecycle client (Prompt 4) + evidence/alert intel
 * client (Prompt 7).
 *
 * B4 is authoritative for call identity:
 *   POST /api/v1/calls                    -> { id: <call_id>, ... }
 *   POST /api/v1/calls/{call_id}/terminate -> { ... , status: "ENDED", ... }
 * B4 is authoritative for intel:
 *   GET  /api/v1/calls/{call_id}/evidence -> { call_id, evidence: [...] }
 *   GET  /api/v1/calls/{call_id}/alerts   -> { call_id, alerts: [...] }
 *   POST /api/v1/alerts/{alert_id}/acknowledge -> alert record
 *
 * The returned call_id is the ONE identity used by WebRTC signaling,
 * the peer call, B1 audio (session_id), and future B2/B3/B4 stages.
 * This module never invents ids, risk, evidence or alerts, and never
 * falls back to fake calls: every failure rejects so the caller can
 * show a real error state.
 */
import type { BackendAlert, BackendEvidenceRecord, Call, ConfidenceLevel, MonitoringState, RiskLevel } from '../types';

const API_BASE =
  (typeof import.meta !== 'undefined'
    ? (import.meta.env?.VITE_API_BASE_URL as string | undefined)
    : undefined) || 'http://localhost:8000/api/v1';

const REQUEST_TIMEOUT_MS = 10000;

async function postJson<T>(path: string, body: unknown): Promise<T> {
  const controller = new AbortController();
  const timer = window.setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);
  let response: Response;
  try {
    response = await fetch(`${API_BASE}${path}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: body === undefined ? undefined : JSON.stringify(body),
      signal: controller.signal,
    });
  } catch (err) {
    throw new Error(
      `backend4: request failed (is Backend 4 running at ${API_BASE}?) — ` +
        (err instanceof Error ? err.message : String(err)),
    );
  } finally {
    window.clearTimeout(timer);
  }
  if (response.status === 404) {
    throw new Backend4NotFoundError(`backend4: not found (${path})`);
  }
  if (!response.ok) {
    let detail = `HTTP ${response.status}`;
    try {
      const data = (await response.json()) as { detail?: unknown };
      if (typeof data.detail === 'string' && data.detail) detail = data.detail;
    } catch {
      // keep default detail
    }
    throw new Error(`backend4: ${detail}`);
  }
  return (await response.json()) as T;
}

export class Backend4NotFoundError extends Error {}

async function getJson<T>(path: string): Promise<T> {
  const controller = new AbortController();
  const timer = window.setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);
  let response: Response;
  try {
    response = await fetch(`${API_BASE}${path}`, { signal: controller.signal });
  } catch (err) {
    throw new Error(
      `backend4: request failed (is Backend 4 running at ${API_BASE}?) — ` +
        (err instanceof Error ? err.message : String(err)),
    );
  } finally {
    window.clearTimeout(timer);
  }
  if (response.status === 404) {
    throw new Backend4NotFoundError(`backend4: not found (${path})`);
  }
  if (!response.ok) {
    let detail = `HTTP ${response.status}`;
    try {
      const data = (await response.json()) as { detail?: unknown };
      if (typeof data.detail === 'string' && data.detail) detail = data.detail;
    } catch {
      // keep default detail
    }
    throw new Error(`backend4: ${detail}`);
  }
  return (await response.json()) as T;
}

/**
 * Minimal B4 call record (subset of to_frontend_dict). Fields beyond id
 * are honest backend nulls until the first RiskUpdate arrives; consumers
 * must coalesce them for display without inventing telemetry.
 */
export interface BackendCallSummary {
  id: string;
  callerName: string | null;
  receiver: string | null;
  startTime: string | null;
  status: string | null;
  monitoringState: string | null;
}

interface RawCallSummary {
  id?: unknown;
  caller?: { name?: unknown } | null;
  receiver?: unknown;
  startTime?: unknown;
  status?: unknown;
  monitoringState?: unknown;
}

function asStringOrNull(value: unknown): string | null {
  return typeof value === 'string' && value ? value : null;
}

/**
 * Create the authoritative call. owner_id is the creator's real display
 * name (dev mode has no auth principals yet); reference_id stays empty
 * (no enrollment in this milestone). Returns the B4 record (id + summary).
 */
export async function createCall(ownerId: string): Promise<BackendCallSummary> {
  if (!ownerId.trim()) {
    throw new Error('backend4: owner display name is required');
  }
  const data = await postJson<RawCallSummary>('/calls', {
    owner_id: ownerId.trim(),
    reference_id: '',
  });
  if (!data || typeof data.id !== 'string' || !data.id) {
    throw new Error('backend4: create response carried no call id');
  }
  return {
    id: data.id,
    callerName: asStringOrNull(data.caller?.name),
    receiver: asStringOrNull(data.receiver),
    startTime: asStringOrNull(data.startTime),
    status: asStringOrNull(data.status),
    monitoringState: asStringOrNull(data.monitoringState),
  };
}

/**
 * Terminate the authoritative call. Idempotent by design: 404 (already
 * gone/unknown) resolves — only transport failures reject. Callers doing
 * best-effort cleanup (leave/unmount) should still catch and ignore.
 */
export async function terminateCall(callId: string): Promise<void> {
  if (!callId) return;
  try {
    await postJson<unknown>(`/calls/${encodeURIComponent(callId)}/terminate`, {});
  } catch (err) {
    if (err instanceof Backend4NotFoundError) return;
    throw err;
  }
}

/**
 * Best-effort termination for unload/unmount paths where awaiting is
 * impossible. Uses keepalive so the browser delivers it during pagehide.
 * Never throws.
 */
export function terminateCallBeacon(callId: string): void {
  if (!callId) return;
  try {
    fetch(`${API_BASE}/calls/${encodeURIComponent(callId)}/terminate`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: '{}',
      keepalive: true,
    }).catch(() => undefined);
  } catch {
    // never throw from cleanup paths
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null;
}

function devWarn(message: string): void {
  if (typeof import.meta !== 'undefined' && import.meta.env?.DEV) {
    // eslint-disable-next-line no-console
    console.warn(message);
  }
}

/**
 * Type guard for one B4 evidence record. Malformed entries are dropped
 * (with a DEV warning), never repaired — repairing would invent data.
 */
export function isBackendEvidenceRecord(value: unknown): value is BackendEvidenceRecord {
  if (!isRecord(value)) return false;
  return (
    typeof value['evidence_id'] === 'string' &&
    !!value['evidence_id'] &&
    typeof value['call_id'] === 'string' &&
    !!value['call_id']
  );
}

/**
 * Type guard for one B4 alert record. Identity is alert_id.
 */
export function isBackendAlert(value: unknown): value is BackendAlert {
  if (!isRecord(value)) return false;
  return (
    typeof value['alert_id'] === 'string' &&
    !!value['alert_id'] &&
    typeof value['call_id'] === 'string' &&
    !!value['call_id']
  );
}

/**
 * Fetch authoritative evidence records for one call.
 * Returns B4's list verbatim (filtered to well-formed records).
 * Empty list = no evidence. Rejects on transport/HTTP failure —
 * callers must keep the empty state, never substitute fixtures.
 */
export async function getCallEvidence(callId: string): Promise<BackendEvidenceRecord[]> {
  if (!callId) throw new Error('backend4: callId is required');
  const data = await getJson<{ call_id?: unknown; evidence?: unknown }>(
    `/calls/${encodeURIComponent(callId)}/evidence`,
  );
  const list = Array.isArray(data?.evidence) ? data.evidence : null;
  if (list === null) {
    throw new Error('backend4: evidence response carried no evidence list');
  }
  const valid = list.filter(isBackendEvidenceRecord);
  if (valid.length !== list.length) {
    devWarn(`[backend4] dropped ${list.length - valid.length} malformed evidence record(s) for ${callId}`);
  }
  return valid;
}

/**
 * Fetch authoritative alerts for one call. Same contract as evidence.
 */
export async function getCallAlerts(callId: string): Promise<BackendAlert[]> {
  if (!callId) throw new Error('backend4: callId is required');
  const data = await getJson<{ call_id?: unknown; alerts?: unknown }>(
    `/calls/${encodeURIComponent(callId)}/alerts`,
  );
  const list = Array.isArray(data?.alerts) ? data.alerts : null;
  if (list === null) {
    throw new Error('backend4: alerts response carried no alerts list');
  }
  const valid = list.filter(isBackendAlert);
  if (valid.length !== list.length) {
    devWarn(`[backend4] dropped ${list.length - valid.length} malformed alert(s) for ${callId}`);
  }
  return valid;
}

/**
 * Acknowledge one B4 alert by its authoritative id. Returns the updated
 * record. Rejects on failure — callers must NOT mark acknowledged locally.
 */
export async function acknowledgeAlert(alertId: string): Promise<BackendAlert> {
  if (!alertId) throw new Error('backend4: alertId is required');
  const data = await postJson<unknown>(`/alerts/${encodeURIComponent(alertId)}/acknowledge`, {});
  if (!isBackendAlert(data)) {
    throw new Error('backend4: acknowledge response carried no alert record');
  }
  return data;
}

/**
 * Merge freshly fetched alerts into existing state, deduplicated by the
 * authoritative alert_id (GET snapshots and WS events converge here).
 * Records whose own call_id differs from the requested call are dropped
 * (call-id isolation) — a compromised/confused backend cannot smear one
 * call's alerts onto another.
 */
export function mergeBackendAlerts(
  existing: BackendAlert[],
  incoming: unknown[],
  callId: string,
): BackendAlert[] {
  // Seed with everything already held (other calls pass through untouched),
  // then overwrite by authoritative alert_id with this call's records.
  const byId = new Map<string, BackendAlert>();
  for (const alert of existing) {
    byId.set(alert.alert_id, alert);
  }
  for (const item of incoming) {
    if (!isBackendAlert(item)) {
      devWarn(`[backend4] dropping malformed alert for ${callId}`);
      continue;
    }
    if (item.call_id !== callId) {
      devWarn(`[backend4] dropping alert ${item.alert_id} for foreign call ${item.call_id}`);
      continue;
    }
    byId.set(item.alert_id, item);
  }
  return [...byId.values()];
}

// ---------------------------------------------------------------------------
// Prompt 8: authoritative active/history lists (B4 source of truth).
// ---------------------------------------------------------------------------

const KNOWN_RISK_LEVELS: RiskLevel[] = ['LOW', 'MEDIUM', 'HIGH'];
const KNOWN_CONFIDENCE: ConfidenceLevel[] = ['LOW', 'MEDIUM', 'HIGH'];
const KNOWN_MONITORING_STATES: MonitoringState[] = [
  'INITIALIZING',
  'ANALYZING',
  'MONITORING_ACTIVE',
  'SUSPICIOUS',
  'ALERT_TRIGGERED',
  'COMPLETED',
];
const KNOWN_CALL_STATUS = ['ACTIVE', 'ENDED', 'FLAGGED', 'INVESTIGATING'] as const;

/**
 * Guard for one B4 call record (to_frontend_dict shape). Only the id is
 * required — every other field is optional/nullable by backend contract.
 */
export function isBackendCallRecord(value: unknown): value is Record<string, unknown> & { id: string } {
  if (!isRecord(value)) return false;
  return typeof value['id'] === 'string' && !!value['id'];
}

function asNumberOrNull(value: unknown): number | null {
  return typeof value === 'number' && Number.isFinite(value) ? value : null;
}

/**
 * Risk bands, mirroring utils/risk.getRiskLevel (kept local so this
 * module stays dependency-free and headless-testable like the rest).
 */
function levelForRisk(risk: number): RiskLevel {
  if (risk < 40) return 'LOW';
  if (risk < 70) return 'MEDIUM';
  return 'HIGH';
}

function asStringOrEmpty(value: unknown): string {
  return typeof value === 'string' ? value : '';
}

/**
 * Fetch the authoritative active-call list. Returns B4's array verbatim
 * (validated as an array; entries validated individually by the mapper).
 * Empty array = no active calls. Rejects on any failure — callers must
 * show error/empty states, never fixtures.
 */
export async function getActiveCalls(): Promise<unknown[]> {
  const data = await getJson<unknown>('/calls/active');
  if (!Array.isArray(data)) {
    throw new Error('backend4: active-calls response was not a list');
  }
  return data;
}

/**
 * Fetch the authoritative call-history list. Same contract as active.
 */
export async function getCallHistory(): Promise<unknown[]> {
  const data = await getJson<unknown>('/calls/history');
  if (!Array.isArray(data)) {
    throw new Error('backend4: call-history response was not a list');
  }
  return data;
}

/**
 * Map one B4 call record to the frontend Call shape (or null when the
 * record lacks an id). Backend nulls become neutral display placeholders
 * — transport normalization, never telemetry: risk metrics stay exactly
 * what B4 reported (or 0 when B4 reported nothing yet), history entries
 * missing timestamp/risk are dropped because they cannot render.
 */
export function mapBackendCallRecord(raw: unknown): Call | null {
  if (!isBackendCallRecord(raw)) {
    devWarn('[backend4] dropping call record without id');
    return null;
  }
  const id = raw['id'];
  const caller = isRecord(raw['caller']) ? raw['caller'] : {};
  const trustScore = asNumberOrNull(caller['trustScore']) ?? 0;
  const risk = asNumberOrNull(raw['currentRisk']) ?? 0;
  const rawLevel = raw['currentRiskLevel'];
  const riskLevel: RiskLevel = KNOWN_RISK_LEVELS.includes(rawLevel as RiskLevel)
    ? (rawLevel as RiskLevel)
    : levelForRisk(risk);
  const rawConfidence = raw['confidence'];
  const confidence: ConfidenceLevel = KNOWN_CONFIDENCE.includes(rawConfidence as ConfidenceLevel)
    ? (rawConfidence as ConfidenceLevel)
    : 'LOW';
  const rawMonitoring = raw['monitoringState'];
  const monitoringState: MonitoringState = KNOWN_MONITORING_STATES.includes(rawMonitoring as MonitoringState)
    ? (rawMonitoring as MonitoringState)
    : 'MONITORING_ACTIVE';
  const rawStatus = raw['status'];
  const status = (KNOWN_CALL_STATUS as readonly string[]).includes(rawStatus as string)
    ? (rawStatus as Call['status'])
    : 'ACTIVE';
  const history: Call['riskHistory'] = [];
  if (Array.isArray(raw['riskHistory'])) {
    for (const entry of raw['riskHistory']) {
      if (!isRecord(entry)) continue;
      const timestamp = asNumberOrNull(entry['timestamp']);
      const entryRisk = asNumberOrNull(entry['risk']);
      if (timestamp === null || entryRisk === null) continue; // cannot render: drop
      history.push({
        timestamp,
        risk: entryRisk,
        syntheticProbability: asNumberOrNull(entry['syntheticProbability']) ?? 0,
      });
    }
  }
  return {
    id,
    caller: {
      id: asStringOrEmpty(caller['id']) || id,
      name: asStringOrEmpty(caller['name']) || 'Unknown caller',
      phone: asStringOrEmpty(caller['phone']),
      organization: asStringOrEmpty(caller['organization']),
      department: asStringOrEmpty(caller['department']),
      trustScore,
      language: asStringOrEmpty(caller['language']),
      isKnownContact: caller['isKnownContact'] === true,
    },
    receiver: asStringOrEmpty(raw['receiver']),
    startTime: asStringOrEmpty(raw['startTime']) || new Date().toISOString(),
    durationSeconds: asNumberOrNull(raw['durationSeconds']) ?? 0,
    currentRisk: risk,
    currentRiskLevel: riskLevel,
    syntheticProbability: asNumberOrNull(raw['syntheticProbability']) ?? 0,
    speakerConsistency: asNumberOrNull(raw['speakerConsistency']) ?? 0,
    contextRisk: asNumberOrNull(raw['contextRisk']) ?? 0,
    confidence,
    status,
    monitoringState,
    detectionEvents: [],
    riskHistory: history,
    evidence: undefined,
    protocol: 'WebRTC',
    codec: 'Opus/48kHz',
    packetLoss: asNumberOrNull(raw['packetLoss']) ?? 0,
    latencyMs: asNumberOrNull(raw['latencyMs']) ?? 0,
    isSimulatedDemo: false,
  };
}

/**
 * Merge a freshly fetched B4 list into live state, keyed by call id.
 *
 * - Fetched records win on id collision (the B4 snapshot carries the
 *   complete server-side risk history, so convergence is lossless).
 * - `local-` records (local audio sessions never sent to B4) are always
 *   preserved — they are real local sessions, not fixtures.
 * - With dropMissing=true (active list): current records B4 no longer
 *   lists are dropped (ended elsewhere).
 * - With dropMissing=false (history): current records B4 doesn't list
 *   are retained, so a failed/partial fetch never destroys archive rows.
 * Pure (headless-testable). Never invents records: output ids ⊆ input ids.
 */
export function mergeCallLists(
  current: Call[],
  fetchedRaw: unknown[],
  dropMissing: boolean,
): Call[] {
  const fetchedById = new Map<string, Call>();
  for (const raw of fetchedRaw) {
    const mapped = mapBackendCallRecord(raw);
    if (mapped) fetchedById.set(mapped.id, mapped);
  }
  const merged: Call[] = [...fetchedById.values()];
  for (const record of current) {
    if (fetchedById.has(record.id)) continue; // authoritative wins
    if (record.id.startsWith('local-') || !dropMissing) {
      merged.push(record);
    }
  }
  return merged;
}
