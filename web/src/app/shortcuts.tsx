import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { ShortcutsDialog } from '../components/ShortcutsDialog';
import { getLastCampaign } from '../lib/lastCampaign';
import { registerShortcut } from '../lib/keyboard';
import { useSearchFocus } from './SearchFocusContext';

/** Global shortcuts from doc 13 §4 (T-115). */
export function GlobalShortcuts() {
  const navigate = useNavigate();
  const { focus } = useSearchFocus();
  const [open, setOpen] = useState(false);
  useEffect(() => {
    const unregister = [
      registerShortcut({
        keys: 'g b',
        description: 'Go to Bench',
        handler: () => {
          void navigate('/');
        },
      }),
      registerShortcut({
        keys: 'g c',
        description: 'Open last campaign console',
        handler: () => {
          const id = getLastCampaign();
          if (id) void navigate(`/campaigns/${id}/console`);
        },
      }),
      registerShortcut({
        keys: '/',
        description: 'Focus search',
        handler: () => {
          focus();
        },
      }),
      registerShortcut({
        keys: '?',
        description: 'Show keyboard shortcuts',
        handler: () => {
          setOpen(true);
        },
      }),
    ];
    return () => {
      unregister.forEach((off) => {
        off();
      });
    };
  }, [focus, navigate]);
  return <ShortcutsDialog open={open} onOpenChange={setOpen} />;
}
