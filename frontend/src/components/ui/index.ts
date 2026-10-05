// Design-system primitives. Import from "components/ui" rather than individual files.
export { Avatar } from "./Avatar";
export { Badge, ConfidenceBadge, StatusBadge, type Tone } from "./Badge";
export { Card, PageHeader, Stat } from "./Card";
export { Empty, ErrorBanner, FieldMessage, Spinner, issueClass } from "./Feedback";
export { Icon, Logo } from "./Icon";
// Formatting helpers are re-exported for convenience; they live in lib/format.
export { fmt, initials, orgLabel } from "../../lib/format";
