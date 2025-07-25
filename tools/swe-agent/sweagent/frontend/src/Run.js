import React, { useState, useRef, useEffect } from "react";
import axios from "axios";
import io from "socket.io-client";
import "./static/run.css";
import AgentFeed from "./components/panels/AgentFeed";
import EnvFeed from "./components/panels/EnvFeed";
import LogPanel from "./components/panels/LogPanel";
import LRunControl from "./components/controls/LRunControl";
import { useImmer } from "use-immer";

const url = ""; // Will get this from .env
// Connect to Socket.io
const socket = io(url);

function Run() {
  const [isConnected, setIsConnected] = useState(socket.connected);
  const [errorBanner, setErrorBanner] = useState("");

  const runConfigDefault = {
    agent: {
      model: {
        model_name: "gpt4",
      },
    },
    environment: {
      bugswarm_image: "",
      repo_path: "",
      base_commit: "",
      environment_setup: {
        input_type: "manual",
        manual: {
          python: "3.10",
          config_type: "manual",
          install: "pip install --editable .",
          install_command_active: true,
          pip_packages: "",
        },
        script_path: {
          script_path: "",
        },
      },
    },
    extra: {
      test_run: false,
    },
  };
  const [runConfig, setRunConfig] = useImmer(runConfigDefault);

  const [agentFeed, setAgentFeed] = useState([]);
  const [envFeed, setEnvFeed] = useState([]);
  const [highlightedStep, setHighlightedStep] = useState(null);
  const [logs, setLogs] = useState("");
  const [isComputing, setIsComputing] = useState(false);

  const hoverTimeoutRef = useRef(null);

  const agentFeedRef = useRef(null);
  const envFeedRef = useRef(null);
  const logsRef = useRef(null);
  const isLogScrolled = useRef(false);
  const isEnvScrolled = useRef(false);
  const isAgentScrolled = useRef(false);

  const [tabKey, setTabKey] = useState("problem");

  const stillComputingTimeoutRef = useRef(null);

  axios.defaults.baseURL = url;

  function scrollToHighlightedStep(highlightedStep, ref) {
    if (highlightedStep && ref.current) {
      console.log(
        "Scrolling to highlighted step",
        highlightedStep,
        ref.current,
      );
      const firstStepMessage = ref.current.querySelector(
        `.step${highlightedStep}`,
      );
      if (firstStepMessage) {
        window.requestAnimationFrame(() => {
          ref.current.scrollTo({
            top: firstStepMessage.offsetTop - ref.current.offsetTop,
            behavior: "smooth",
          });
        });
      }
    }
  }

  function getOtherFeed(feedRef) {
    return feedRef === agentFeedRef ? envFeedRef : agentFeedRef;
  }

  const handleMouseEnter = (item, feedRef) => {
    if (isComputing) {
      return;
    }

    const highlightedStep = item.step;

    if (hoverTimeoutRef.current) {
      clearTimeout(hoverTimeoutRef.current);
    }

    hoverTimeoutRef.current = setTimeout(() => {
      if (!isComputing) {
        setHighlightedStep(highlightedStep);
        scrollToHighlightedStep(highlightedStep, getOtherFeed(feedRef));
      }
    }, 250);
  };

  const handleMouseLeave = () => {
    console.log("Mouse left");
    if (hoverTimeoutRef.current) {
      clearTimeout(hoverTimeoutRef.current);
    }
    setHighlightedStep(null);
  };

  const requeueStopComputeTimeout = () => {
    // clearTimeout(stillComputingTimeoutRef.current);
    // setIsComputing(true);
    // stillComputingTimeoutRef.current = setTimeout(() => {
    //   setIsComputing(false);
    //   console.log("No activity for 30s, setting isComputing to false");
    // }, 30000);
  };

  // Handle form submission
  const handleSubmit = async (event) => {
    setTabKey(null);
    setIsComputing(true);
    event.preventDefault();
    setAgentFeed([]);
    setEnvFeed([]);
    setLogs("");
    setHighlightedStep(null);
    setErrorBanner("");
    try {
      await axios.get(`/run`, {
        params: { runConfig: JSON.stringify(runConfig) },
      });
    } catch (error) {
      console.error("Error:", error);
    }
  };

  const handleStop = async () => {
    setIsComputing(false);
    try {
      const response = await axios.get("/stop");
      console.log(response.data);
    } catch (error) {
      console.error("Error stopping:", error);
    }
  };

  const checkScrollPosition = (ref, scrollStateRef, offset = 0) => {
    scrollStateRef.current =
      ref.current.scrollTop + ref.current.clientHeight + offset <
      ref.current.scrollHeight;
  };

  const scrollToBottom = (ref, scrollStateRef) => {
    if (!scrollStateRef.current) {
      ref.current.scrollTop = ref.current.scrollHeight;
    }
  };

  const scrollDetectedLog = () =>
    checkScrollPosition(logsRef, isLogScrolled, 58);
  const scrollLog = () => scrollToBottom(logsRef, isLogScrolled);

  const scrollDetectedEnv = () =>
    checkScrollPosition(envFeedRef, isEnvScrolled);
  const scrollEnv = () => scrollToBottom(envFeedRef, isEnvScrolled);

  const scrollDetectedAgent = () =>
    checkScrollPosition(agentFeedRef, isAgentScrolled);
  const scrollAgent = () => scrollToBottom(agentFeedRef, isAgentScrolled);

  // Use effect to listen to socket updates
  React.useEffect(() => {
    logsRef.current.addEventListener("scroll", scrollDetectedLog, {
      passive: true,
    });
    envFeedRef.current.addEventListener("scroll", scrollDetectedEnv, {
      passive: true,
    });
    agentFeedRef.current.addEventListener("scroll", scrollDetectedAgent, {
      passive: true,
    });

    const handleUpdate = (data) => {
      requeueStopComputeTimeout();
      if (data.feed === "agent") {
        setAgentFeed((prevMessages) => [
          ...prevMessages,
          {
            type: data.type,
            message: data.message,
            format: data.format,
            step: data.thought_idx,
          },
        ]);
        if (envFeedRef.current) {
          setTimeout(() => {
            scrollEnv();
          }, 100);
        }
      } else if (data.feed === "env") {
        setEnvFeed((prevMessages) => [
          ...prevMessages,
          {
            message: data.message,
            type: data.type,
            format: data.format,
            step: data.thought_idx,
          },
        ]);
        if (agentFeedRef.current) {
          setTimeout(() => {
            scrollAgent();
          }, 100);
        }
      }
      return () => {
        logsRef.current.removeEventListener("scroll", scrollDetectedLog);
        envFeedRef.current.removeEventListener("scroll", scrollDetectedEnv);
        agentFeedRef.current.removeEventListener("scroll", scrollDetectedAgent);
      };
    };

    const handleUpdateBanner = (data) => {
      setErrorBanner(data.message);
    };

    const handleLogMessage = (data) => {
      requeueStopComputeTimeout();
      setLogs((prevLogs) => prevLogs + data.message);
      if (logsRef.current) {
        setTimeout(() => {
          scrollLog();
        }, 100);
      }
    };

    const handleFinishedRun = (data) => {
      setIsComputing(false);
    };

    socket.on("update", handleUpdate);
    socket.on("log_message", handleLogMessage);
    socket.on("update_banner", handleUpdateBanner);
    socket.on("finish_run", handleFinishedRun);
    socket.on("connect", () => {
      console.log("Connected to server");
      setIsConnected(true);
      setErrorBanner("");
    });

    socket.on("disconnect", () => {
      console.log("Disconnected from server");
      setIsConnected(false);
      setErrorBanner("Connection to flask server lost, please restart it.");
      setIsComputing(false);
      scrollLog(); // reveal copy button
    });

    socket.on("connect_error", (error) => {
      setIsConnected(false);
      setErrorBanner(
        "Failed to connect to the flask server, please restart it.",
      );
      setIsComputing(false);
      scrollLog(); // reveal copy button
    });

    return () => {
      socket.off("update", handleUpdate);
      socket.off("log_message", handleLogMessage);
      socket.off("finish_run", handleFinishedRun);
      socket.off("connect");
      socket.off("disconnect");
      socket.off("connect_error");
      socket.off("update_banner", handleUpdateBanner);
    };
  }, []);

  function renderErrorMessage() {
    if (errorBanner) {
      return (
        <div className="alert alert-danger" role="alert">
          {errorBanner}
          <br />
          If you think this was a bug, please head over to{" "}
          <a
            href="https://github.com/princeton-nlp/swe-agent/issues"
            target="blank"
          >
            our GitHub issue tracker
          </a>
          , check if someone has already reported the issue, and if not, create
          a new issue. Please include the full log, all settings that you
          entered, and a screenshot of this page.
        </div>
      );
    }
    return null;
  }

  return (
    <div className="container-demo">
      {renderErrorMessage()}
      <LRunControl
        isComputing={isComputing}
        isConnected={isConnected}
        handleStop={handleStop}
        handleSubmit={handleSubmit}
        tabKey={tabKey}
        setTabKey={setTabKey}
        runConfig={runConfig}
        setRunConfig={setRunConfig}
        runConfigDefault={runConfigDefault}
      />
      <div id="demo">
        <hr />
        <div className="panels">
          <AgentFeed
            feed={agentFeed}
            highlightedStep={highlightedStep}
            handleMouseEnter={handleMouseEnter}
            handleMouseLeave={handleMouseLeave}
            selfRef={agentFeedRef}
            otherRef={envFeedRef}
          />
          <EnvFeed
            feed={envFeed}
            highlightedStep={highlightedStep}
            handleMouseEnter={handleMouseEnter}
            handleMouseLeave={handleMouseLeave}
            selfRef={envFeedRef}
            otherRef={agentFeedRef}
          />
          <LogPanel logs={logs} logsRef={logsRef} isComputing={isComputing} />
        </div>
      </div>
      <hr />
    </div>
  );
}

export default Run;
