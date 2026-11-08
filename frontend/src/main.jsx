import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import Sesion from "./Sesion.jsx";
import "./estilos.css";

createRoot(document.getElementById("raiz")).render(
  <StrictMode>
    <Sesion />
  </StrictMode>,
);
