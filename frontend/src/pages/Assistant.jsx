import { ChatWindow } from "../assistant/components/ChatWindow";
import "../assistant/assistant.css";

/**
 * The grounded assistant, as a dashboard page.
 *
 * Everything it needs lives under src/assistant: its own components, its own
 * theme and copy files, and a stylesheet scoped to .dq-assistant so it cannot
 * reach the dashboard around it.
 */
function Assistant() {
  return <ChatWindow />;
}

export default Assistant;
