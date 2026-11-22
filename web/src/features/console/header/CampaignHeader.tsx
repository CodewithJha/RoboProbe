import { useRef } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { type Campaign, useCampaignCommand } from '../../../api/hooks';
import { ProblemView } from '../../../app/ProblemView';

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
  const dialog = useRef<HTMLDialogElement>(null);
  const client = useQueryClient();
  const command = useCampaignCommand(campaign.id);
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
      {command.isPending ? <p role="status">Updating campaign…</p> : null}
      {command.isError ? <ProblemView error={command.error} /> : null}
      <dialog ref={dialog} aria-label="Cancel campaign confirmation">
        <h2>Cancel campaign?</h2>
        <p>Pending runs will be cancelled. In-flight runs may still finish.</p>
        <form method="dialog">
          <button>Keep campaign</button>
          <button
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
