import React from "react";
import { createRoot } from "react-dom/client";
import App from "./App.jsx";
import Upload from "./Upload.jsx";
import "./styles.css";

// /upload/<token> is the customer's page; everything else is the staff app.
const upload = window.location.pathname.match(/^\/upload\/([\w-]+)/);
createRoot(document.getElementById("root")).render(upload ? <Upload token={upload[1]} /> : <App />);
