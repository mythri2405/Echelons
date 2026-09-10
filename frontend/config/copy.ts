/**
 * Every string the operator reads.
 *
 * No component contains user-facing text of its own. Reword the product here.
 * The tone to keep: plain, direct, no exclamation marks, no emoji, nothing that
 * sounds pleased with itself. This is read on a working deck.
 */

export const copy = {
  app: {
    name: 'DeepEcho',
    subtitle: 'Side-scan sonar decision support',
  },

  status: {
    checking: 'Connecting to the assistant',
    ready: 'Ready',
    degraded: 'Index unavailable',
    offline: 'Backend unreachable',
    corpusSummary: (documents: number, chunks: number) =>
      `${documents} reference documents, ${chunks} indexed passages`,
    providerSummary: (provider: string, model: string) => `${provider} / ${model}`,
    detectorStub: 'Detector is a stub. Uploaded tiles return a placeholder detection, not a real one.',
    detectorModels: (models: string[]) =>
      models.length === 0 ? '' : `detector: ${models.join(' and ')}`,
  },

  empty: {
    title: 'Ask about a sonar contact',
    body:
      'Every answer is drawn from a fixed set of published marine references and cites them. ' +
      'Where those references do not cover something, the assistant says so rather than filling the gap.',
    examplesLabel: 'Try',
    examples: [
      'Who do I report a suspected mine to?',
      'The classifier could not identify this contact. What do I do?',
      'How do I tell a manufactured object from a rock on side scan?',
      'Write me an incident report for this detection.',
    ],
  },

  composer: {
    placeholder: 'Ask about this contact',
    placeholderStreaming: 'Answering',
    send: 'Send',
    stop: 'Stop',
    hint: 'Enter to send, Shift and Enter for a new line',
  },

  roles: {
    user: 'You',
    assistant: 'Assistant',
  },

  badge: {
    confidence: (value: number) => `Classifier confidence ${Math.round(value * 100)}%`,
    severityLabel: 'Risk',
    severity: {
      high: 'High',
      medium: 'Medium',
      low: 'Low',
      unknown: 'Unknown',
    },
    intent: {
      question: 'Question',
      explain: 'Detection brief',
      anomaly: 'Unidentified object',
      report: 'Incident report',
    },
    anomaly: 'Unknown object, treated as an anomaly',
    unclassified: 'Unclassified',
  },

  notice: {
    ungroundedTitle: 'Unverified',
    ungroundedBody:
      'No matching reference was found for this answer. Confirm it manually before acting on it.',
    refusalTitle: 'Partly outside the references',
    refusalBody:
      'Part of this answer is the assistant declining to fill a gap the references do not cover. ' +
      'The missing detail is not an omission, it is unavailable.',
    anomalyTitle: 'Object is unidentified',
    anomalyBody:
      'Nothing below identifies this object. Similar known objects are listed as possibilities only, ' +
      'and it stays unidentified until a qualified expert rules.',
    coverageGapTitle: 'No reference covers this class',
    coverageGapBody:
      'The detector named a class the reference documents do not describe. The assistant will say so ' +
      'rather than answering from a document about a different kind of object. Treat what follows as ' +
      'the generic unidentified-object handling, not as guidance for this class.',
    stubDetectionTitle: 'Placeholder detection',
    stubDetectionBody:
      'This record came from the stub detector, not a trained model. It is synthetic and is not evidence.',
  },

  matches: {
    title: 'Nearest known objects',
    caveat:
      'A similarity ranking, not a probability and not an identification. A higher score does not make an identity more likely to be true.',
    similarity: 'Similarity',
    confirms: 'Would confirm',
    rulesOut: 'Would rule out',
    hazard: 'Hazard class',
  },

  citations: {
    panelTitle: 'Source',
    listTitle: 'Sources',
    close: 'Close',
    authority: 'Published by',
    section: 'Section',
    status: 'Status',
    similarity: 'Retrieval score',
    openPdf: 'Open the original publication',
    noPdf: 'No original file is attached to this document',
    markerTitle: (n: number) => `Open source ${n}`,
    count: (n: number) => (n === 1 ? '1 source' : `${n} sources`),
  },

  upload: {
    button: 'Upload sonar tile',
    uploading: 'Reading tile',
    disabled: 'Tile upload is switched off',
    rejected: 'That file type is not accepted',
    detectionsFound: (n: number) => (n === 1 ? '1 contact found' : `${n} contacts found`),
    noDetections: 'No contacts were found in that tile',
    attached: 'Attached to this conversation',
    // Sent automatically after an upload, so a tile produces a briefing without
    // the operator having to think of a question first.
    autoBrief: 'Brief me on this contact.',
    contactsLabel: 'Contacts in this tile',
    contact: (n: number, cls: string, confidence: number) =>
      `${n}. ${cls} ${Math.round(confidence * 100)}%`,
    downgraded: 'Class withheld, reported as unidentified',
    detach: 'Remove',
  },

  detection: {
    title: 'Detection on screen',
    none: 'No detection attached',
    fields: {
      object_class: 'Class',
      confidence: 'Confidence',
      bbox: 'Bounding box',
      depth_m: 'Depth (m)',
      latitude: 'Latitude',
      longitude: 'Longitude',
      timestamp: 'Time',
      sensor: 'Sensor',
      platform: 'Platform',
      notes: 'Notes',
      visual_description: 'Description',
      detector_model: 'Detected by',
      detector_class: 'Detector class',
      second_opinion: 'Second opinion',
      downgraded_from: 'Class withheld',
    } as Record<string, string>,
  },

  error: {
    title: 'Request failed',
    backendDown:
      'The assistant backend did not respond. Check that it is running, then send the message again.',
    generic: 'Something went wrong while answering. Nothing above was changed.',
    streamInterrupted:
      'The answer stopped partway. What arrived is shown above and is still cited; the rest is missing.',
    retry: 'Try again',
  },
} as const
