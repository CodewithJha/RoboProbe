import campaignPage from '../src/test/fixtures/campaigns.json' with { type: 'json' };
import comparison from '../src/test/fixtures/comparison.json' with { type: 'json' };
import modePage from '../src/test/fixtures/modes.json' with { type: 'json' };
import config from './e2e.config.json' with { type: 'json' };

const campaign = campaignPage.items[0];
if (!campaign) throw new Error('The checked-in E2E seed has no campaign.');
const mode = modePage.items.find((item) => item.code === config.seed.modeCode);
if (!mode?.medoid_run_id) throw new Error('The checked-in E2E mode has no medoid run.');
const strategies = Object.keys(comparison.strategies);
if (!strategies.length) throw new Error('The checked-in E2E comparison has no strategies.');

export const seed = {
  campaign,
  campaignModes: modePage.items,
  medoid: { id: mode.medoid_run_id, modeCode: mode.code },
  experimentId: comparison.experiment_id,
  strategies,
};
