import { useParams } from 'react-router-dom';
import { InsightsPanel } from '../casebook/insights/InsightsPanel';
export function Component() {
  const { id } = useParams();
  return (
    <section>
      <h1>Insights</h1>
      {id ? <InsightsPanel campaignId={id} /> : null}
    </section>
  );
}
