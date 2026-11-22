import { useState } from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { api, getEtag, ProblemError, requireData, type Schema } from '../../../api/client';

export function ThreatsNotes({ experiment }: { experiment: Schema['ExperimentOut'] }) {
  const [draft, setDraft] = useState(experiment.notes ?? '');
  const [saved, setSaved] = useState(experiment.notes ?? '');
  const [etag, setEtag] = useState(() => getEtag(`/api/v1/experiments/${experiment.id}`));
  const cache = useQueryClient();
  const save = useMutation({
    mutationFn: async ({
      notes,
      version,
    }: {
      notes: string;
      version: string;
    }): Promise<Schema['ExperimentOut']> =>
      requireData<Schema['ExperimentOut']>(
        // @ts-expect-error experiment PATCH is not yet in the generated client
        await api.PATCH('/api/v1/experiments/{experiment_id}', {
          params: { path: { experiment_id: experiment.id } },
          headers: { 'If-Match': version },
          body: { notes },
        }),
      ),
    onSuccess(response: Schema['ExperimentOut']) {
      setSaved(response.notes ?? '');
      setEtag(getEtag(`/api/v1/experiments/${experiment.id}`));
      void cache.invalidateQueries({ queryKey: ['experiments', experiment.id], exact: true });
    },
  });
  const refresh = useMutation({
    mutationFn: async () =>
      requireData(
        await api.GET('/api/v1/experiments/{experiment_id}', {
          params: { path: { experiment_id: experiment.id } },
        }),
      ),
    onSuccess(response: Schema['ExperimentOut']) {
      setSaved(response.notes ?? '');
      setEtag(getEtag(`/api/v1/experiments/${experiment.id}`));
      save.reset();
    },
  });
  const conflict = save.error instanceof ProblemError && save.error.status === 412;
  return (
    <section>
      <h2>Threats to validity</h2>
      <form
        onSubmit={(event) => {
          event.preventDefault();
          if (etag && draft !== saved && !conflict)
            save.mutate({ notes: draft, version: etag });
        }}
      >
        <label>
          Experiment notes{' '}
          <textarea
            value={draft}
            onChange={(event) => {
              setDraft(event.target.value);
            }}
          />
        </label>
        <button
          disabled={!etag || draft === saved || save.isPending || conflict || refresh.isPending}
        >
          Save notes
        </button>
      </form>
      {save.isSuccess && draft === saved && <p role="status">Notes saved.</p>}
      {conflict && (
        <div role="alert">
          <p>
            Someone saved a newer version. Load their notes before deciding whether to save your
            draft.
          </p>
          <button
            type="button"
            disabled={refresh.isPending}
            onClick={() => {
              refresh.mutate();
            }}
          >
            Load latest notes
          </button>
        </div>
      )}
      {save.isError && !conflict && <p role="alert">{save.error.message}</p>}
      {refresh.isError && <p role="alert">{refresh.error.message}</p>}
      {refresh.isSuccess && draft !== saved && (
        <details open>
          <summary>Latest saved notes</summary>
          <p>{saved !== '' ? saved : 'No saved notes.'}</p>
        </details>
      )}
      {!etag && <p>The server did not provide a version for safe editing.</p>}
    </section>
  );
}
