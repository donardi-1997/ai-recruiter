function BrandMark({ compact = false }) {
  return (
    <span className={`asiati-brand ${compact ? "asiati-brand--compact" : ""}`}>
      <span className="asiati-mark" aria-hidden="true">
        <span>A</span>
        <i />
      </span>
      <span className="asiati-wordmark">
        <strong>ASIATI</strong>
        <small>Talent intelligence</small>
      </span>
    </span>
  );
}

export default BrandMark;
