import { useLocation } from "react-router-dom";

import { ChatWindow } from "../assistant/components/ChatWindow";
import "../assistant/assistant.css";

/**
 * The grounded assistant, as a dashboard page.
 *
 * Everything it needs lives under src/assistant: its own components, its own
 * theme and copy files, and a stylesheet scoped to .dq-assistant so it cannot
 * reach the dashboard around it.
 *
 * The hazard map hands a hotspot over through router state rather than through
 * a detection record. That is deliberate. A detection record would be remapped
 * onto the assistant's own severity table, and the same hotspot would then
 * carry one urgency on the map and a different one beside the answer. The map
 * owns urgency, so its severity travels with the context and is displayed as
 * given.
 */
function Assistant() {
  const { state } = useLocation();

  return (
    <ChatWindow
      surveyContext={state?.surveyContext ?? null}
      initialQuestion={state?.question ?? null}
    />
  );
}

export default Assistant;
