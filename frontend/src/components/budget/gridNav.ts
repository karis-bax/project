/** The id of the neighbouring cell in the given direction, or undefined at an
 * edge. Used to decide whether Tab/Shift+Tab should move within the grid
 * (preventDefault) or be allowed to leave it (at the first/last cell). */
export function neighborId(
  ids: number[],
  id: number,
  direction: 1 | -1,
): number | undefined {
  const index = ids.indexOf(id)
  if (index === -1) return undefined
  return ids[index + direction]
}
