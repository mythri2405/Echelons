import { priorityOptions, tierStyle } from "../config"

/**
 * Class, severity and priority filters.
 *
 * Every option is derived from the export that is loaded, never hard-coded.
 * A survey containing no mines has no "mine" option, so the control can never
 * offer a filter that would return nothing, and a detector trained on classes
 * nobody here has heard of still populates the list correctly.
 */
function Filters({ classes, tiers, value, onChange, resultCount, totalCount }) {
  const set = (key) => (event) => onChange({ ...value, [key]: event.target.value })

  return (
    <div className="sv-filters">
      <label className="sv-filter">
        <span>Class</span>
        <select value={value.objectClass} onChange={set("objectClass")}>
          <option value="all">All classes</option>
          {classes.map((name) => (
            <option key={name} value={name}>
              {name}
            </option>
          ))}
        </select>
      </label>

      <label className="sv-filter">
        <span>Severity</span>
        <select value={value.tier} onChange={set("tier")}>
          <option value="all">All severities</option>
          {tiers.map((tier) => (
            <option key={tier} value={tier}>
              {(tierStyle[tier] || { label: tier }).label}
            </option>
          ))}
        </select>
      </label>

      <label className="sv-filter">
        <span>Priority</span>
        <select value={value.priority} onChange={set("priority")}>
          {priorityOptions.map((option) => (
            <option key={option.value} value={option.value}>
              {option.label}
            </option>
          ))}
        </select>
      </label>

      <span className="sv-filter-count">
        {resultCount === totalCount
          ? `${totalCount} hotspot${totalCount === 1 ? "" : "s"}`
          : `${resultCount} of ${totalCount} hotspots`}
      </span>
    </div>
  )
}

export default Filters
