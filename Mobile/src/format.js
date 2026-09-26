/** "1 point", "5 points", "-1 point" - a rating with the right word. */
export function pointsText(value) {
  const n = value ?? 0;
  return `${n} ${Math.abs(n) === 1 ? 'point' : 'points'}`;
}
