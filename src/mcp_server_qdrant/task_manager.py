import json
import os
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional


@dataclass
class Task:
    id: str
    title: str
    description: str
    done: bool = False
    approved: bool = False
    completedDetails: str = ""


@dataclass
class RequestEntry:
    requestId: str
    originalRequest: str
    splitDetails: str
    tasks: List[Task]
    completed: bool = False


@dataclass
class TaskManagerFile:
    requests: List[RequestEntry] = field(default_factory=list)


class TaskManager:
    def __init__(self, file_path: str = None):
        self.file_path = file_path if file_path else os.path.join(os.path.expanduser("~"), "Documents", "tasks.json")
        self.request_counter = 0
        self.task_counter = 0
        self.data: TaskManagerFile = TaskManagerFile()
        self.load_tasks()

    def load_tasks(self):
        try:
            with open(self.file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                self.data = TaskManagerFile(
                    requests=[
                        RequestEntry(
                            requestId=req["requestId"],
                            originalRequest=req["originalRequest"],
                            splitDetails=req.get("splitDetails", req["originalRequest"]),
                            tasks=[
                                Task(
                                    id=task["id"],
                                    title=task["title"],
                                    description=task["description"],
                                    done=task.get("done", False),
                                    approved=task.get("approved", False),
                                    completedDetails=task.get("completedDetails", ""),
                                )
                                for task in req["tasks"]
                            ],
                            completed=req.get("completed", False),
                        )
                        for req in data["requests"]
                    ]
                )
                all_task_ids = []
                all_request_ids = []

                for req in self.data.requests:
                    req_num = int(req.requestId.replace("req-", ""))
                    all_request_ids.append(req_num)
                    for t in req.tasks:
                        t_num = int(t.id.replace("task-", ""))
                        all_task_ids.append(t_num)

                self.request_counter = max(all_request_ids) if all_request_ids else 0
                self.task_counter = max(all_task_ids) if all_task_ids else 0

        except (FileNotFoundError, json.JSONDecodeError):
            self.data = TaskManagerFile()

    def save_tasks(self):
        try:
            with open(self.file_path, "w", encoding="utf-8") as f:
                json.dump(self.data_to_dict(), f, indent=2)
        except IOError as e:
            if "EROFS" in str(e):
                print("EROFS: read-only file system. Cannot save tasks.")
            raise

    def data_to_dict(self):
        return {
            "requests": [
                {
                    "requestId": req.requestId,
                    "originalRequest": req.originalRequest,
                    "splitDetails": req.splitDetails,
                    "tasks": [
                        {
                            "id": task.id,
                            "title": task.title,
                            "description": task.description,
                            "done": task.done,
                            "approved": task.approved,
                            "completedDetails": task.completedDetails,
                        }
                        for task in req.tasks
                    ],
                    "completed": req.completed,
                }
                for req in self.data.requests
            ]
        }

    def format_task_progress_table(self, requestId: str) -> str:
        req = next((r for r in self.data.requests if r.requestId == requestId), None)
        if not req:
            return "Request not found"

        table = "\nProgress Status:\n"
        table += "| Task ID | Title | Description | Status | Approval |\n"
        table += "|----------|----------|------|------|----------|\n"

        for task in req.tasks:
            status = "✅ Done" if task.done else "🔄 In Progress"
            approved = "✅ Approved" if task.approved else "⏳ Pending"
            table += f"| {task.id} | {task.title} | {task.description} | {status} | {approved} |\n"

        return table

    def format_requests_list(self) -> str:
        output = "\nRequests List:\n"
        output += "| Request ID | Original Request | Total Tasks | Completed | Approved |\n"
        output += "|------------|------------------|-------------|-----------|----------|\n"

        for req in self.data.requests:
            total_tasks = len(req.tasks)
            completed_tasks = sum(1 for t in req.tasks if t.done)
            approved_tasks = sum(1 for t in req.tasks if t.approved)
            output += f"| {req.requestId} | {req.originalRequest[:30]}{'...' if len(req.originalRequest) > 30 else ''} | {total_tasks} | {completed_tasks} | {approved_tasks} |\n"

        return output

    def request_planning(self, originalRequest: str, tasks: List[Dict[str, str]], splitDetails: Optional[str] = None) -> \
    Dict[str, Any]:
        self.load_tasks()
        self.request_counter += 1
        requestId = f"req-{self.request_counter}"

        new_tasks: List[Task] = []
        for task_def in tasks:
            self.task_counter += 1
            new_tasks.append(
                Task(
                    id=f"task-{self.task_counter}",
                    title=task_def["title"],
                    description=task_def["description"],
                )
            )

        self.data.requests.append(
            RequestEntry(
                requestId=requestId,
                originalRequest=originalRequest,
                splitDetails=splitDetails if splitDetails is not None else originalRequest,
                tasks=new_tasks,
            )
        )

        self.save_tasks()

        progress_table = self.format_task_progress_table(requestId)

        return {
            "status": "planned",
            "requestId": requestId,
            "totalTasks": len(new_tasks),
            "tasks": [{"id": t.id, "title": t.title, "description": t.description} for t in new_tasks],
            "message": f"Tasks have been successfully added. Please use 'get_next_task' to retrieve the first task.\n{progress_table}",
        }

    def get_next_task(self, requestId: str) -> Dict[str, Any]:
        self.load_tasks()
        req = next((r for r in self.data.requests if r.requestId == requestId), None)
        if not req:
            return {"status": "error", "message": "Request not found"}
        if req.completed:
            return {"status": "already_completed", "message": "Request already completed."}

        next_task = next((t for t in req.tasks if not t.done), None)
        if not next_task:
            all_done = all(t.done for t in req.tasks)
            if all_done and not req.completed:
                progress_table = self.format_task_progress_table(requestId)
                return {
                    "status": "all_tasks_done",
                    "message": f"All tasks have been completed. Awaiting request completion approval.\n{progress_table}",
                }
            return {"status": "no_next_task", "message": "No undone tasks found."}

        progress_table = self.format_task_progress_table(requestId)
        return {
            "status": "next_task",
            "task": {
                "id": next_task.id,
                "title": next_task.title,
                "description": next_task.description,
            },
            "message": f"Next task is ready. Task approval will be required after completion.\n{progress_table}",
        }

    def mark_task_done(self, requestId: str, taskId: str, completedDetails: Optional[str] = None) -> Dict[str, Any]:
        self.load_tasks()
        req = next((r for r in self.data.requests if r.requestId == requestId), None)
        if not req:
            return {"status": "error", "message": "Request not found"}
        task = next((t for t in req.tasks if t.id == taskId), None)
        if not task:
            return {"status": "error", "message": "Task not found"}
        if task.done:
            return {"status": "already_done", "message": "Task is already marked done."}

        task.done = True
        task.completedDetails = completedDetails if completedDetails is not None else ""
        self.save_tasks()
        return {
            "status": "task_marked_done",
            "requestId": req.requestId,
            "task": {
                "id": task.id,
                "title": task.title,
                "description": task.description,
                "completedDetails": task.completedDetails,
                "approved": task.approved,
            },
        }

    def approve_task_completion(self, requestId: str, taskId: str) -> Dict[str, Any]:
        self.load_tasks()
        req = next((r for r in self.data.requests if r.requestId == requestId), None)
        if not req:
            return {"status": "error", "message": "Request not found"}
        task = next((t for t in req.tasks if t.id == taskId), None)
        if not task:
            return {"status": "error", "message": "Task not found"}
        if not task.done:
            return {"status": "error", "message": "Task not done yet."}
        if task.approved:
            return {"status": "already_approved", "message": "Task already approved."}

        task.approved = True
        self.save_tasks()
        return {
            "status": "task_approved",
            "requestId": req.requestId,
            "task": {
                "id": task.id,
                "title": task.title,
                "description": task.description,
                "completedDetails": task.completedDetails,
                "approved": task.approved,
            },
        }

    def approve_request_completion(self, requestId: str) -> Dict[str, Any]:
        self.load_tasks()
        req = next((r for r in self.data.requests if r.requestId == requestId), None)
        if not req:
            return {"status": "error", "message": "Request not found"}

        all_done = all(t.done for t in req.tasks)
        if not all_done:
            return {"status": "error", "message": "Not all tasks are done."}
        all_approved = all(t.done and t.approved for t in req.tasks)
        if not all_approved:
            return {"status": "error", "message": "Not all done tasks are approved."}

        req.completed = True
        self.save_tasks()
        return {
            "status": "request_approved_complete",
            "requestId": req.requestId,
            "message": "Request is fully completed and approved.",
        }

    def open_task_details(self, taskId: str) -> Dict[str, Any]:
        self.load_tasks()
        for req in self.data.requests:
            target = next((t for t in req.tasks if t.id == taskId), None)
            if target:
                return {
                    "status": "task_details",
                    "requestId": req.requestId,
                    "originalRequest": req.originalRequest,
                    "splitDetails": req.splitDetails,
                    "completed": req.completed,
                    "task": {
                        "id": target.id,
                        "title": target.title,
                        "description": target.description,
                        "done": target.done,
                        "approved": target.approved,
                        "completedDetails": target.completedDetails,
                    },
                }
        return {"status": "task_not_found", "message": "No such task found"}

    def list_requests(self) -> Dict[str, Any]:
        self.load_tasks()
        requests_list = self.format_requests_list()
        return {
            "status": "requests_listed",
            "message": f"Current requests in the system:\n{requests_list}",
            "requests": [
                {
                    "requestId": req.requestId,
                    "originalRequest": req.originalRequest,
                    "totalTasks": len(req.tasks),
                    "completedTasks": sum(1 for t in req.tasks if t.done),
                    "approvedTasks": sum(1 for t in req.tasks if t.approved),
                }
                for req in self.data.requests
            ],
        }

    def add_tasks_to_request(self, requestId: str, tasks: List[Dict[str, str]]) -> Dict[str, Any]:
        self.load_tasks()
        req = next((r for r in self.data.requests if r.requestId == requestId), None)
        if not req:
            return {"status": "error", "message": "Request not found"}
        if req.completed:
            return {"status": "error", "message": "Cannot add tasks to completed request"}

        new_tasks: List[Task] = []
        for task_def in tasks:
            self.task_counter += 1
            new_tasks.append(
                Task(
                    id=f"task-{self.task_counter}",
                    title=task_def["title"],
                    description=task_def["description"],
                )
            )

        req.tasks.extend(new_tasks)
        self.save_tasks()

        progress_table = self.format_task_progress_table(requestId)
        return {
            "status": "tasks_added",
            "message": f"Added {len(new_tasks)} new tasks to request.\n{progress_table}",
            "newTasks": [{"id": t.id, "title": t.title, "description": t.description} for t in new_tasks],
        }

    def update_task(self, requestId: str, taskId: str, updates: Dict[str, str]) -> Dict[str, Any]:
        self.load_tasks()
        req = next((r for r in self.data.requests if r.requestId == requestId), None)
        if not req:
            return {"status": "error", "message": "Request not found"}

        task = next((t for t in req.tasks if t.id == taskId), None)
        if not task:
            return {"status": "error", "message": "Task not found"}
        if task.done:
            return {"status": "error", "message": "Cannot update completed task"}

        if "title" in updates:
            task.title = updates["title"]
        if "description" in updates:
            task.description = updates["description"]

        self.save_tasks()

        progress_table = self.format_task_progress_table(requestId)
        return {
            "status": "task_updated",
            "message": f"Task {taskId} has been updated.\n{progress_table}",
            "task": {
                "id": task.id,
                "title": task.title,
                "description": task.description,
            },
        }

    def delete_task(self, requestId: str, taskId: str) -> Dict[str, Any]:
        self.load_tasks()
        req = next((r for r in self.data.requests if r.requestId == requestId), None)
        if not req:
            return {"status": "error", "message": "Request not found"}

        task_index = -1
        for i, t in enumerate(req.tasks):
            if t.id == taskId:
                task_index = i
                break

        if task_index == -1:
            return {"status": "error", "message": "Task not found"}
        if req.tasks[task_index].done:
            return {"status": "error", "message": "Cannot delete completed task"}

        del req.tasks[task_index]
        self.save_tasks()

        progress_table = self.format_task_progress_table(requestId)
        return {
            "status": "task_deleted",
            "message": f"Task {taskId} has been deleted.\n{progress_table}",
        }
