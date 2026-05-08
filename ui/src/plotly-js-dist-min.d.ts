/** plotly.js-dist-min ships without `.d.ts`; PlotlyChart casts the default export. */
declare module "plotly.js-dist-min" {
  const Plotly: unknown;
  export default Plotly;
}
