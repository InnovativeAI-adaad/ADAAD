class BaseAgent:
    name: str = "base"
    role: str = "executor"     # planner|executor|critic|verifier|explainer
    authority: str = "propose"  # propose|commit|read_only

    def plan(self, goal, ctx):  # optional
        raise NotImplementedError

    def act(self, task, ctx):  # required for executors
        raise NotImplementedError

    def verify(self, artifact, ctx):  # optional for verifiers
        return {"ok": True}
