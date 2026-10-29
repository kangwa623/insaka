import { Component } from "react";

// If a screen fails to render, show a calm message and a way back instead of a blank page.
export default class ErrorBoundary extends Component {
  constructor(props) {
    super(props);
    this.state = { failed: false };
  }

  static getDerivedStateFromError() {
    return { failed: true };
  }

  render() {
    if (!this.state.failed) return this.props.children;
    return (
      <div className="phone">
        <div className="phone-card">
          <div className="phone-brand">Insaka</div>
          <h1>Something went wrong on this screen</h1>
          <p>Your work on the server is safe. Reload to continue.</p>
          <button className="primary wide" onClick={() => window.location.reload()}>Reload</button>
        </div>
      </div>
    );
  }
}
