import factory from 'react-plotly.js/factory';
import Plotly from 'plotly.js/lib/core';
import heatmap from 'plotly.js/lib/heatmap';
import scatter from 'plotly.js/lib/scatter';
import box from 'plotly.js/lib/box';
import contour from 'plotly.js/lib/contour';

// Plotly core bundle registers trace modules without full package typings.
// eslint-disable-next-line @typescript-eslint/no-unsafe-call, @typescript-eslint/no-unsafe-member-access
Plotly.register([heatmap, scatter, box, contour]);

export default factory(Plotly);
