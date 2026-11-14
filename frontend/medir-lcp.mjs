// RNF-001: Largest Contentful Paint (LCP) del dashboard con red Fast 3G, meta ≤ 2,5 s.
//
// Abre cada página con el caché vacío, con la red Fast 3G de Chrome DevTools (562,5 ms de
// latencia, 1,44 Mbit/s de bajada y 675 kbit/s de subida) y el procesador 4 veces más lento (como
// Lighthouse en móvil), y lee el LCP que da el propio navegador. Mide la pantalla de inicio de
// sesión y, ya con sesión, la vista general y el detalle de un sensor. Necesita el servicio
// corriendo con datos y un usuario del dashboard:
//
//   cd frontend
//   npm install                     (una vez; trae Playwright)
//   npx playwright install chromium (una vez)
//   $env:CORREO_LCP="<correo de un usuario>"; $env:CONTRASENA_LCP="<su contraseña>"
//   npm run lcp                     (o: node medir-lcp.mjs https://127.0.0.1:8001)
//
// Con MOVIL=1 mide en pantalla de teléfono (390 × 844). El resultado queda en
// ../docs/rendimiento/lcp.json (o lcp-movil.json).

import { mkdirSync, writeFileSync } from "node:fs";
import { chromium } from "playwright";

const BASE = (process.argv[2] || process.env.URL_DASHBOARD || "https://127.0.0.1:8001").replace(/\/$/, "");
const N = Number(process.env.REPETICIONES || 5);
const MOVIL = Boolean(process.env.MOVIL);
const META_MS = 2500;
const FAST_3G = { offline: false, latency: 562.5, downloadThroughput: (1.6 * 1024 * 1024 / 8) * 0.9,
                  uploadThroughput: (750 * 1024 / 8) * 0.9 };
const PAGINAS = [["", false, "Inicio de sesión"], ["#/general", true, "Vista general"],
                 ["#/sensor/J224", true, "Detalle de un sensor"]];

async function medir(navegador, ruta, conSesion) {
  const ctx = await navegador.newContext({
    viewport: MOVIL ? { width: 390, height: 844 } : { width: 1366, height: 768 },
    isMobile: MOVIL, hasTouch: MOVIL, ignoreHTTPSErrors: true,       // certificado propio del servicio
  });
  if (conSesion) {
    const r = await ctx.request.post(`${BASE}/api/sesion`, {
      data: { correo: process.env.CORREO_LCP, contrasena: process.env.CONTRASENA_LCP } });
    if (!r.ok()) throw new Error(`No se pudo iniciar sesión (${r.status()}): revisa CORREO_LCP y CONTRASENA_LCP`);
  }
  const pagina = await ctx.newPage();
  const cdp = await ctx.newCDPSession(pagina);
  await cdp.send("Network.enable");
  await cdp.send("Network.setCacheDisabled", { cacheDisabled: true });
  await cdp.send("Network.emulateNetworkConditions", FAST_3G);
  await cdp.send("Emulation.setCPUThrottlingRate", { rate: 4 });
  let bytes = 0;
  cdp.on("Network.loadingFinished", (e) => { bytes += e.encodedDataLength; });
  await pagina.addInitScript(() => {
    window.__lcp = [];
    window.__datos = null;
    new PerformanceObserver((l) => {
      for (const e of l.getEntries()) window.__lcp.push({ t: e.startTime, elemento: e.element?.tagName ?? e.url });
    }).observe({ type: "largest-contentful-paint", buffered: true });
    // cuándo aparecen las tarjetas con los valores de los sensores (ya hay datos en pantalla)
    new MutationObserver(() => {
      if (window.__datos === null && document.querySelector(".tarjeta .valor")) window.__datos = performance.now();
    }).observe(document, { subtree: true, childList: true });
  });
  await pagina.goto(`${BASE}/${ruta}`, { waitUntil: "load", timeout: 120000 });
  await pagina.waitForTimeout(12000);        // que terminen de llegar los datos; sin tocar la página
  const r = await pagina.evaluate(() => ({
    lcp: window.__lcp.at(-1), datos: window.__datos,
    fcp: performance.getEntriesByName("first-contentful-paint")[0]?.startTime,
  }));
  await ctx.close();
  return { lcp_ms: Math.round(r.lcp.t), elemento: r.lcp.elemento, fcp_ms: Math.round(r.fcp),
           datos_ms: r.datos === null ? null : Math.round(r.datos), kb: Math.round(bytes / 1024) };
}

const navegador = await chromium.launch();
const resultado = { url: BASE, fecha: new Date().toISOString(), pantalla: MOVIL ? "teléfono 390 × 844" : "1366 × 768",
                    red: "Fast 3G (562,5 ms, 1,44 Mbit/s bajada, 675 kbit/s subida)", cpu: "4 veces más lento",
                    meta_ms: META_MS, paginas: [] };
for (const [ruta, conSesion, nombre] of PAGINAS) {
  const veces = [];
  for (let i = 0; i < N; i++) veces.push(await medir(navegador, ruta, conSesion));
  const lcp = veces.map((v) => v.lcp_ms).sort((a, b) => a - b);
  const p = { pagina: nombre, ruta: ruta || "/", lcp_ms: lcp, lcp_mediana_ms: lcp[Math.floor(lcp.length / 2)],
              lcp_max_ms: lcp.at(-1), cumple: lcp.at(-1) <= META_MS, elemento_lcp: veces[0].elemento,
              fcp_ms: veces.map((v) => v.fcp_ms), datos_en_pantalla_ms: veces.map((v) => v.datos_ms),
              kb_transferidos: veces[0].kb };
  resultado.paginas.push(p);
  console.log(`${nombre.padEnd(22)} LCP mediana ${p.lcp_mediana_ms} ms · máximo ${p.lcp_max_ms} ms · `
              + `${p.cumple ? "cumple" : "NO cumple"} (≤ ${META_MS} ms) · ${p.kb_transferidos} KB`);
}
await navegador.close();
mkdirSync("../docs/rendimiento", { recursive: true });
writeFileSync(`../docs/rendimiento/${MOVIL ? "lcp-movil" : "lcp"}.json`, JSON.stringify(resultado, null, 2) + "\n");
process.exit(resultado.paginas.every((p) => p.cumple) ? 0 : 1);
