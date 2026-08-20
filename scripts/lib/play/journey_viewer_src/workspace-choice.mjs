function usable(item) {
  return Boolean(item?.graph_ready || item?.projectable)
}

/** Choose a stable first view without overriding an explicit URL or user choice. */
export function chooseWorkspace(workspaces = [], {current = '', requested = '', selectedId = ''} = {}) {
  const currentItem = workspaces.find((item) => item.id === current && usable(item))
  if (currentItem) return currentItem
  const requestedItem = requested
    ? workspaces.find((item) => usable(item) && (
      item.id === requested || item.workspace === requested || item.workspace_path === requested
    ))
    : null
  if (requestedItem) return requestedItem
  const tutorial = workspaces.find((item) => item.tutorial && usable(item))
  if (tutorial) return tutorial
  return workspaces.find((item) => item.id === selectedId && usable(item))
    || workspaces.find(usable)
    || null
}
