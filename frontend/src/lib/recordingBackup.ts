/**
 * RNF-06 (partial): local-only protection against losing an in-progress
 * recording to a crash/accidental reload *before* the user clicks "Parar".
 * Not a substitute for server-side resilience — there's no sync while
 * recording, and a very long recording still grows this store roughly
 * linearly (documented limitation in frontend/README.md).
 *
 * Only IndexedDB glue lives here (integration code, exercised manually —
 * see README); `assembleRecordingBlob` is the one pure/testable piece.
 */

const DB_NAME = "phi-scribe-recording";
const DB_VERSION = 1;
const STORE_NAME = "backups";
// Single fixed key: this UI only ever has one active recording at a time,
// so there's no need to key by a session id.
const BACKUP_KEY = "active";

export interface RecordingBackupMeta {
  startedAt: string; // ISO 8601
  mimeType: string;
  deviceId: string | null;
}

export interface RecordingBackupRecord extends RecordingBackupMeta {
  chunks: Blob[];
  // Earlier segments from a recording that was interrupted (tab closed/crash)
  // and then continued — see continueRecording() in useAudioRecorder.ts.
  // Optional so records written before this field existed still parse.
  previousSegments?: Blob[];
}

function isIndexedDbAvailable(): boolean {
  return typeof indexedDB !== "undefined";
}

function openDb(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    if (!isIndexedDbAvailable()) {
      reject(new Error("IndexedDB is not available"));
      return;
    }
    const request = indexedDB.open(DB_NAME, DB_VERSION);
    request.onupgradeneeded = () => {
      const db = request.result;
      if (!db.objectStoreNames.contains(STORE_NAME)) {
        db.createObjectStore(STORE_NAME);
      }
    };
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error ?? new Error("Failed to open IndexedDB"));
  });
}

function putRecord(db: IDBDatabase, record: RecordingBackupRecord): Promise<void> {
  return new Promise((resolve, reject) => {
    const tx = db.transaction(STORE_NAME, "readwrite");
    tx.objectStore(STORE_NAME).put(record, BACKUP_KEY);
    tx.oncomplete = () => resolve();
    tx.onerror = () => reject(tx.error);
  });
}

function getRecord(db: IDBDatabase): Promise<RecordingBackupRecord | null> {
  return new Promise((resolve, reject) => {
    const tx = db.transaction(STORE_NAME, "readonly");
    const request = tx.objectStore(STORE_NAME).get(BACKUP_KEY);
    request.onsuccess = () => resolve((request.result as RecordingBackupRecord | undefined) ?? null);
    request.onerror = () => reject(request.error);
  });
}

function deleteRecord(db: IDBDatabase): Promise<void> {
  return new Promise((resolve, reject) => {
    const tx = db.transaction(STORE_NAME, "readwrite");
    tx.objectStore(STORE_NAME).delete(BACKUP_KEY);
    tx.oncomplete = () => resolve();
    tx.onerror = () => reject(tx.error);
  });
}

/**
 * Call once when a recording starts. Overwrites (and thus discards) any prior
 * unrecovered backup — unless `previousSegments` is passed (continueRecording
 * carrying forward an earlier interrupted take), in which case those segments
 * are preserved so the final upload can still include them.
 */
export async function startRecordingBackup(
  meta: RecordingBackupMeta,
  previousSegments: Blob[] = [],
): Promise<void> {
  try {
    const db = await openDb();
    await putRecord(db, { ...meta, chunks: [], previousSegments });
    db.close();
  } catch {
    // Best-effort — IndexedDB might be unavailable (private mode, quota).
  }
}

/** Call from MediaRecorder's ondataavailable — appends without needing the caller to track chunks itself. */
export async function appendRecordingBackupChunk(chunk: Blob): Promise<void> {
  try {
    const db = await openDb();
    const existing = await getRecord(db);
    if (existing) {
      await putRecord(db, { ...existing, chunks: [...existing.chunks, chunk] });
    }
    db.close();
  } catch {
    // best-effort
  }
}

/** Call once a recording either uploads successfully or is explicitly discarded. */
export async function clearRecordingBackup(): Promise<void> {
  try {
    const db = await openDb();
    await deleteRecord(db);
    db.close();
  } catch {
    // best-effort
  }
}

export async function loadRecordingBackup(): Promise<RecordingBackupRecord | null> {
  try {
    const db = await openDb();
    const record = await getRecord(db);
    db.close();
    return record;
  } catch {
    return null;
  }
}

export function assembleRecordingBlob(record: RecordingBackupRecord): Blob {
  return new Blob(record.chunks, { type: record.mimeType });
}

/**
 * Full ordered list of segments for a backup record: any earlier interrupted
 * takes (already-complete Blobs from a previous continueRecording), followed
 * by the current in-progress segment (if it has any chunks). Each element
 * uploads as its own file; the backend concatenates them in order.
 */
export function assembleAllSegments(record: RecordingBackupRecord): Blob[] {
  const segments = [...(record.previousSegments ?? [])];
  if (record.chunks.length > 0) {
    segments.push(assembleRecordingBlob(record));
  }
  return segments;
}
