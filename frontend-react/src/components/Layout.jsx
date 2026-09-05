import Navbar from "./Navbar";
import Footer from "./Footer";

function Layout({ children }) {
  return (
    <div className="app-layout">
      <a className="skip-link" href="#main-content">Saltar al contenido</a>
      <Navbar />
      <div className="app-content">
        <main id="main-content" className="app-main">{children}</main>
        <Footer />
      </div>
    </div>
  );
}

export default Layout;
