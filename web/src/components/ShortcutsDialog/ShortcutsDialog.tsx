import * as Dialog from '@radix-ui/react-dialog';
import { useSyncExternalStore } from 'react';
import { getKeyboardManager, type ShortcutInfo, type ShortcutScope } from '../../lib/keyboard';
import styles from './ShortcutsDialog.module.css';

function group(shortcuts: ShortcutInfo[]) {
  const buckets = new Map<ShortcutScope, typeof shortcuts>();
  shortcuts.forEach((item) => {
    const scope = item.scope;
    const groupItems = buckets.get(scope) ?? [];
    groupItems.push(item);
    buckets.set(scope, groupItems);
  });
  return buckets;
}

export function ShortcutsDialog({
  open,
  onOpenChange,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const manager = getKeyboardManager();
  useSyncExternalStore(
    (listener) => manager.subscribeList(listener),
    () => manager.listRevision(),
    () => 0,
  );
  const shortcuts = manager.list();
  const groups = group(shortcuts);
  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <Dialog.Portal>
        <Dialog.Overlay className={styles['overlay']} />
        <Dialog.Content className={styles['content']} aria-describedby={undefined}>
          <Dialog.Title>Keyboard shortcuts</Dialog.Title>
          <Dialog.Description className={styles['lead']}>
            Press <kbd>?</kbd> anytime to reopen this panel. Shortcuts pause while you type in a field.
          </Dialog.Description>
          {(['global', 'feature'] as const).map((scope) => {
            const items = groups.get(scope);
            if (!items?.length) return null;
            return (
              <section key={scope}>
                <h2>{scope === 'global' ? 'Everywhere' : 'This screen'}</h2>
                <table>
                  <caption className={styles['hidden']}>
                    {scope === 'global' ? 'Global shortcuts' : 'Feature shortcuts'}
                  </caption>
                  <tbody>
                    {items.map((item) => (
                      <tr key={item.keys}>
                        <th scope="row">
                          <kbd>{item.keys}</kbd>
                        </th>
                        <td>{item.description}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </section>
            );
          })}
          <Dialog.Close className={styles['close']}>Close</Dialog.Close>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}