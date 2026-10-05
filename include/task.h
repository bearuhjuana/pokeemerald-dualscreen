#ifndef GUARD_TASK_H
#define GUARD_TASK_H

#define HEAD_SENTINEL 0xFE
#define TAIL_SENTINEL 0xFF
#define TASK_NONE TAIL_SENTINEL

#define NUM_TASKS 16
#define NUM_TASK_DATA 16

typedef void (*TaskFunc)(u8 taskId);

struct Task
{
    TaskFunc func;
    bool8 isActive;
    u8 prev;
    u8 next;
    u8 priority;
    s16 data[NUM_TASK_DATA];
#ifdef PORTABLE_64BIT
    TaskFunc followupFunc;
#endif
};

extern struct Task gTasks[];

void ResetTasks(void);
u8 CreateTask(TaskFunc func, u8 priority);
void DestroyTask(u8 taskId);
void RunTasks(void);
void TaskDummy(u8 taskId);
void SetTaskFuncWithFollowupFunc(u8 taskId, TaskFunc func, TaskFunc followupFunc);
void SwitchTaskToFollowupFunc(u8 taskId);
bool8 FuncIsActiveTask(TaskFunc func);
u8 FindTaskIdByFunc(TaskFunc func);
u8 GetTaskCount(void);
void SetWordTaskArg(u8 taskId, u8 dataElem, u32 value);
u32 GetWordTaskArg(u8 taskId, u8 dataElem);

#ifdef PORTABLE_64BIT
// Pointer arguments occupy four halfwords instead of a 32-bit word.
void SetPointerTaskArg(u8 taskId, u8 dataElem, void *value);
void *GetPointerTaskArg(u8 taskId, u8 dataElem);
#endif

#endif // GUARD_TASK_H
