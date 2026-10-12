export interface RequiredField {
  target: string;
  message: string;
}

export function focusRequiredField(target: string): void {
  const field = document.getElementById(target);
  if (!field) return;
  field.focus({ preventScroll: true });
  field.scrollIntoView({ block: 'center', behavior: 'auto' });
}
