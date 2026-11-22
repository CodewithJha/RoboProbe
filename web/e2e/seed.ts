import campaignPage from '../src/test/fixtures/campaigns.json' with { type: 'json' };
import modePage from '../src/test/fixtures/modes.json' with { type: 'json' };
import representativeRun from '../src/test/fixtures/run_detail.json' with { type: 'json' };

const campaign = campaignPage.items[0];
if (!campaign) throw new Error('The checked-in E2E seed has no campaign.');

export const seed = { campaign, campaignModes: modePage.items, representativeRun };
