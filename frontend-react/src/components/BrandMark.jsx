// eslint-disable-next-line no-unused-vars
import React from "react";
import "./BrandMark.css";

function BrandMark({ compact = false }) {
  return (
    <span className={`asiati-brand ${compact ? "asiati-brand--compact" : ""}`}>
      <img className="asiati-logo" src="/asiati-logo.svg" alt="ASIATI" />
      <span className="asiati-brand-tagline">Talent intelligence</span>
    </span>
  );
}

export default BrandMark;
