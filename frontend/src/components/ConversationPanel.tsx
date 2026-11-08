import { useEffect, useId, useRef, type ReactNode } from 'react'
import { createPortal } from 'react-dom'

export function ConversationPanel({ children, footer, onClose, open = true }: { children: ReactNode; footer?: ReactNode; onClose: () => void; open?: boolean }) {
  const titleId = useId()
  const dialog = useRef<HTMLElement>(null)
  const onCloseRef = useRef(onClose)
  onCloseRef.current = onClose
  useEffect(() => {
    if (!open || !dialog.current) return
    const element = dialog.current
    const opener = document.activeElement instanceof HTMLElement ? document.activeElement : null
    const previous: [HTMLElement, boolean][] = []
    for (const node of Array.from(document.body.children)) {
      if (node instanceof HTMLElement && !node.contains(element)) { previous.push([node, node.inert]); node.inert = true }
    }
    const controls = () => Array.from(element.querySelectorAll<HTMLElement>('button, a[href], select, input, summary, [tabindex="0"]')).filter(item => !item.hasAttribute('disabled') && !item.closest('[hidden]'))
    controls()[0]?.focus()
    const keydown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') { event.preventDefault(); onCloseRef.current(); return }
      if (event.key !== 'Tab') return
      const items = controls()
      const first = items[0]
      const last = items.at(-1)
      if (!first) { event.preventDefault(); element.focus(); return }
      if (event.shiftKey && (document.activeElement === first || !element.contains(document.activeElement))) { event.preventDefault(); last?.focus() }
      else if (!event.shiftKey && (document.activeElement === last || !element.contains(document.activeElement))) { event.preventDefault(); first.focus() }
    }
    document.addEventListener('keydown', keydown)
    return () => {
      document.removeEventListener('keydown', keydown)
      for (const [node, inert] of previous) node.inert = inert
      if (opener?.isConnected) opener.focus()
    }
  }, [open])
  return createPortal(<div className="drawer-backdrop conversation-backdrop" hidden={!open} inert={!open} onMouseDown={event => { if (event.target === event.currentTarget) onClose() }}>
    <aside ref={dialog} className="drawer conversation-panel" role="dialog" aria-modal="true" aria-labelledby={titleId} tabIndex={-1}>
      <header className="drawer-header"><h2 id={titleId}>Разговор за столом</h2><button className="icon-button" aria-label="Закрыть разговор" onClick={onClose}>×</button></header>
      <div className="conversation-panel-body">{children}</div>
      {footer && <footer className="conversation-panel-footer">{footer}</footer>}
    </aside>
  </div>, document.body)
}
