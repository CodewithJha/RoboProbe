declare module 'plotly.js/lib/core' {
  import * as Plotly from 'plotly.js';
  export default Plotly;
}
declare module 'plotly.js/lib/heatmap' {
  import type { register } from 'plotly.js';
  const trace: Exclude<Parameters<typeof register>[0], unknown[]>;
  export default trace;
}
declare module 'plotly.js/lib/scatter' {
  import type { register } from 'plotly.js';
  const trace: Exclude<Parameters<typeof register>[0], unknown[]>;
  export default trace;
}
declare module 'plotly.js/lib/box' {
  import type { register } from 'plotly.js';
  const trace: Exclude<Parameters<typeof register>[0], unknown[]>;
  export default trace;
}
declare module 'plotly.js/lib/contour' {
  import type { register } from 'plotly.js';
  const trace: Exclude<Parameters<typeof register>[0], unknown[]>;
  export default trace;
}
