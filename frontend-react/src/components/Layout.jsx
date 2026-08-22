import Navbar from "./Navbar";
import Footer from "./Footer";

function Layout({ children }) {
  return (
    <div className="app-layout">
      <Navbar />

      <main className="app-main">{children}</main>

      <Footer />
    </div>
  );
}

export default Layout;
