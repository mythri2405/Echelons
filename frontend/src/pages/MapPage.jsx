import SurveyHazardMap from "../survey/SurveyHazardMap";

/**
 * The survey hazard map, as a dashboard page.
 *
 * Everything it needs lives under src/survey: its own components, its own
 * config and copy, and a stylesheet scoped to .sv- so it cannot reach the
 * dashboard around it. Same arrangement as src/assistant.
 *
 * This replaces the placeholder that previously read "Geographical sonar
 * detections will appear here", which is what this page is.
 */
function MapPage() {
  return <SurveyHazardMap />;
}

export default MapPage;
