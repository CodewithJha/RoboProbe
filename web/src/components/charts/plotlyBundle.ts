import factory from 'react-plotly.js/factory';
import Plotly from 'plotly.js/lib/core';
import heatmap from 'plotly.js/lib/heatmap';
import scatter from 'plotly.js/lib/scatter';
import box from 'plotly.js/lib/box';
import contour from 'plotly.js/lib/contour';

Plotly.register([heatmap, scatter, box, contour]);

export default factory(Plotly);
