from enum import Enum, auto


class TestcaseState(Enum):
    """Execution states for concolic execution state machine."""

    SELECT = (
        auto()
    )  # Select an EXISTING test case to execute. The start of each iteration.
    SUMMARIZE = auto()  # Analyze execution paths and generate constraints
    SOLVE = auto()  # Solve constraints to generate new inputs
    EXECUTE = (
        auto()
    )  # Execute the NEW test case, collect traces, and check if target lines are covered
    REVIEW_SOLVER = auto()  # Review solver solution
    REVIEW_SOLVER_EXECUTE = auto()  # Execute corrected solver solution
    REVIEW_SUMMARY = auto()  # Problem in summarizer, try a different branch
    REVIEW_SUMMARY_SOLVE = auto()  # Solve constraints after reviewing summarizer
    REVIEW_SUMMARY_EXECUTE = auto()  # Execute after reviewing summarizer
    FINISHED = auto()  # Finished

    def __str__(self):
        return self.name


class ConcolicExecutionState(Enum):
    """Execution states for concolic execution state machine."""

    SELECT = (
        auto()
    )  # Select an EXISTING test case to execute. The start of each iteration.
    SUMMARIZE = (
        auto()
    )  # Analyze execution summary of selected test case, select SEVERAL target branches and generate their path constraints, and submit them to the solver (in parallel)
    SOLVE_AND_EXECUTE = (
        auto()
    )  # Waiting for all path constraints to be solved and executed
    ITERATION_FINISHED = auto()  # This iteration is finished, go to next iteration

    def __str__(self):
        return self.name
