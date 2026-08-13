# Time Tracker App

A time-stamping app for tracking work.

## Core concept

- Work is organized into **projects**, each with **subtasks**.
- There is a single timer for the whole app, not one per project or subtask.
- Starting the timer requires attaching it to one subtask (under a project).
- Only one timer can run at a time — starting a new timer stops/finishes whatever is currently running.

## Working in this repo

- This project folder is currently empty — there's no existing codebase yet, so early sessions here will likely be scaffolding the app from scratch.
- When adding features, keep the "one active timer at a time" rule central to the data model and UI — it shouldn't be possible to have two running timers simultaneously, even across different projects.
- Ask before introducing new frameworks/dependencies if the tech stack (language, UI framework, storage) hasn't been decided yet.
