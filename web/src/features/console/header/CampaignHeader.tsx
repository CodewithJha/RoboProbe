import { useRef, type KeyboardEvent } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { type Campaign, useCampaignCommand } from '../../../api/hooks';
import { ProblemView } from '../../../app/ProblemView';
import { ExportReportButton } from '../../reports/ExportReportButton';
import { useRuntimeConfig } from '../../../app/contexts';

const actions = {
  CREATED: ['start', 'cancel'],
  RUNNING: ['pause', 'cancel'],
  PAUSED: ['resume', 'cancel'],
  ANALYZING: [],
  COMPLETED: [],
  FAILED: [],
  CANCELLED: [],
} as const satisfies Record<Campaign['status'], readonly string[]>;

const labels = { start: 'Start', pause: 'Pause', cancel: 'Cancel campaign', resume: 'Resume' };
type Command = keyof typeof labels;

export function CampaignHeader({ campaign }: { campaign: Campaign }) {
  const { featureFlags } = useRuntimeConfig();
  const dialog = useRef<HTMLDialogElement>(null);
  const keepButton = useRef<HTMLButtonElement>(null);
  const confirmButton = useRef<HTMLButtonElement>(null);
  const client = useQueryClient();
  const command = useCampaignCommand(campaign.id);

  function cycleDialogFocus(event: KeyboardEvent<HTMLButtonElement>, backwards: boolean) {
    if (event.key !== 'Tab' || event.shiftKey !== backwards) return;
    event.preventDefault();
    (backwards ? confirmButton.current : keepButton.current)?.focus();
  }

  function send(action: Command) {
    command.mutate(action, {
      onSuccess: (updated) => client.setQueryData(['campaigns', campaign.id], updated),
      onError: () => {
        void client.invalidateQueries({ queryKey: ['campaigns', campaign.id] });
      },
    });
  }
  return (
    <header>
      <p className="page-label">Campaign Console</p>
      <h1>{campaign.name}</h1>
      <p>
        {campaign.strategy.id} · {campaign.backend} · seed {campaign.strategy.seed} ·{' '}
        {campaign.status}
      </p>
      {actions[campaign.status].map((action) => (
        <button
          key={action}
          type="button"
          disabled={command.isPending}
          onClick={() => {
            if (action === 'cancel') dialog.current?.showModal();
            else send(action);
          }}
        >
          {labels[action]}
        </button>
      ))}
      {featureFlags.reports ? (
        <ExportReportButton kind="campaign" id={campaign.id} label="Export report" />
      ) : null}
      {command.isPending ? <p role="status">Updating campaign…</p> : null}
      {command.isError ? <ProblemView error={command.error} /> : null}
      <dialog ref={dialog} aria-label="Cancel campaign confirmation">
        <h2>Cancel campaign?</h2>
        <p>Pending runs will be cancelled. In-flight runs may still finish.</p>
        <form method="dialog">
          <button
            ref={keepButton}
            onKeyDown={(event) => {
              cycleDialogFocus(event, true);
            }}
          >
            Keep campaign
          </button>
          <button
            ref={confirmButton}
            onKeyDown={(event) => {
              cycleDialogFocus(event, false);
            }}
            onClick={() => {
              send('cancel');
            }}
          >
            Confirm cancellation
          </button>
        </form>
      </dialog>
    </header>
  );
}
