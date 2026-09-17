// eslint-disable-next-line no-unused-vars
import React from "react";
import "./BrandMark.css";

function BrandMark({ compact = false }) {
  return (
    <span className={`asiati-brand ${compact ? "asiati-brand--compact" : ""}`}>
      <span className="asiati-logo-frame asiati-logo-frame--round">
        <img className="asiati-logo" src="/asiati-logo.svg" alt="ASIATI" />
      </span>
      <span className="asiati-brand-tagline">Talent intelligence</span>
    </span>
  );
}

export default BrandMark;
