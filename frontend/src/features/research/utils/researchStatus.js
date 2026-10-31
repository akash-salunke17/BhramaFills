export function getStatusBadgeClass(status) {
  switch (status) {
    case "In Progress":
      return "bg-blue-500/10 text-blue-700 border-blue-500/20";
    case "Completed":
      return "bg-emerald-500/10 text-emerald-700 border-emerald-500/20";
    case "Archived":
      return "bg-zinc-500/10 text-zinc-700 border-zinc-500/20";
    case "Draft":
    default:
      return "bg-amber-500/10 text-amber-700 border-amber-500/20";
  }
}
