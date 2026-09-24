// eslint-disable-next-line no-unused-vars
import React from "react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import Training from "../pages/Training";

vi.mock("../api/client", () => ({
  default: {
    get: vi.fn(),
    post: vi.fn(),
    put: vi.fn(),
  },
}));

vi.mock("../context/SessionContext", () => ({
  useSession: vi.fn(),
}));

import api from "../api/client";
import { useSession } from "../context/SessionContext";


function renderPage() {
  return render(
    <MemoryRouter>
      <Training />
    </MemoryRouter>,
  );
}


const assignment = {
  id: "assignment-1",
  status: "ASSIGNED",
  course: {
    id: "course-1",
    title: "Inducción ASIATI",
    description: "Conoce la empresa.",
    module_count: 1,
    lesson_count: 1,
    completed_lessons: 0,
    progress_percent: 0,
    estimated_minutes: 2,
    remaining_minutes: 2,
    next_lesson_id: "lesson-1",
  },
};


const employeeDetail = {
  assignment_id: "assignment-1",
  assignment_status: "ASSIGNED",
  course: {
    id: "course-1",
    title: "Inducción ASIATI",
    description: "Conoce la empresa.",
    status: "PUBLISHED",
    progress_percent: 0,
    lesson_count: 1,
    completed_lessons: 0,
    estimated_minutes: 2,
    remaining_minutes: 2,
    next_lesson_id: "lesson-1",
    modules: [
      {
        id: "module-1",
        title: "Bienvenida",
        description: null,
        position: 1,
        lesson_count: 1,
        completed_lessons: 0,
        progress_percent: 0,
        is_complete: false,
        estimated_minutes: 2,
        lessons: [
          {
            id: "lesson-1",
            title: "Quiénes somos",
            description: "Introducción.",
            video_url: "https://cdn.example.com/intro.mp4",
            duration_seconds: 120,
            content_type: "VIDEO",
            external_url: null,
            estimated_minutes: 2,
            is_optional: false,
            position: 1,
            completed: false,
          },
        ],
      },
    ],
  },
};


describe("Training platform", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("lets an employee consume only assigned training and mark a lesson complete", async () => {
    useSession.mockReturnValue({
      principal: {
        profile: { id: "employee-1", first_name: "Ana" },
      },
      hasPermission: (permission) => [
        "training.read",
        "training.consume",
      ].includes(permission),
    });

    api.get.mockImplementation((url) => {
      if (url === "/training/me") {
        return Promise.resolve({ data: { items: [assignment] } });
      }
      if (url === "/training/me/courses/course-1") {
        return Promise.resolve({ data: employeeDetail });
      }
      return Promise.reject(new Error(`Unexpected GET ${url}`));
    });

    api.post.mockResolvedValueOnce({
      data: {
        ...employeeDetail,
        assignment_status: "COMPLETED",
        course: {
          ...employeeDetail.course,
          progress_percent: 100,
          completed_lessons: 1,
          modules: [
            {
              ...employeeDetail.course.modules[0],
              lessons: [
                {
                  ...employeeDetail.course.modules[0].lessons[0],
                  completed: true,
                },
              ],
            },
          ],
        },
      },
    });

    renderPage();

    expect((await screen.findAllByText("Inducción ASIATI")).length).toBeGreaterThan(0);
    expect((await screen.findAllByText("Quiénes somos")).length).toBeGreaterThan(0);
    expect(screen.queryByRole("button", { name: "+ Crear curso" })).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Marcar completada" }));

    await waitFor(() => {
      expect(api.post).toHaveBeenCalledWith(
        "/training/me/lessons/lesson-1/complete",
      );
    });
  });

  it("restores and saves onboarding checklist progress", async () => {
    useSession.mockReturnValue({
      principal: {
        profile: { id: "employee-1", first_name: "Ana" },
      },
      hasPermission: (permission) => [
        "training.read",
        "training.consume",
      ].includes(permission),
    });

    const checklistAssignment = {
      ...assignment,
      course: {
        ...assignment.course,
        title: "Onboarding ASIATI",
        lesson_count: 1,
        completed_lessons: 0,
        progress_percent: 0,
        next_lesson_id: "checklist-1",
      },
    };

    let currentDetail = {
      assignment_id: "assignment-1",
      assignment_status: "ASSIGNED",
      course: {
        ...employeeDetail.course,
        title: "Onboarding ASIATI",
        lesson_count: 1,
        completed_lessons: 0,
        progress_percent: 0,
        next_lesson_id: "checklist-1",
        modules: [
          {
            id: "module-role",
            title: "Tu cargo en ASIATI",
            position: 1,
            lesson_count: 1,
            completed_lessons: 0,
            progress_percent: 0,
            is_complete: false,
            estimated_minutes: 5,
            lessons: [
              {
                id: "checklist-1",
                title: "Tu rol y tus primeros días",
                description: "Checklist inicial.",
                content_type: "CHECKLIST",
                checklist_items: [
                  "Conozco el alcance principal de mi cargo.",
                  "Sé quién es mi líder o punto de apoyo.",
                ],
                checklist_completed_items: [0],
                estimated_minutes: 5,
                is_optional: false,
                completed: false,
                position: 1,
              },
            ],
          },
        ],
      },
    };

    api.get.mockImplementation((url) => {
      if (url === "/training/me") {
        return Promise.resolve({ data: { items: [checklistAssignment] } });
      }
      if (url === "/training/me/courses/course-1") {
        return Promise.resolve({ data: currentDetail });
      }
      return Promise.reject(new Error(`Unexpected GET ${url}`));
    });

    api.put.mockImplementation((url, body) => {
      if (url !== "/training/me/lessons/checklist-1/checklist") {
        return Promise.reject(new Error(`Unexpected PUT ${url}`));
      }
      currentDetail = {
        ...currentDetail,
        assignment_status: "COMPLETED",
        course: {
          ...currentDetail.course,
          completed_lessons: 1,
          progress_percent: 100,
          next_lesson_id: null,
          modules: [
            {
              ...currentDetail.course.modules[0],
              completed_lessons: 1,
              progress_percent: 100,
              is_complete: true,
              lessons: [
                {
                  ...currentDetail.course.modules[0].lessons[0],
                  checklist_completed_items: body.completed_items,
                  completed: true,
                },
              ],
            },
          ],
        },
      };
      return Promise.resolve({ data: currentDetail });
    });

    renderPage();

    const first = await screen.findByLabelText("Conozco el alcance principal de mi cargo.");
    const second = screen.getByLabelText("Sé quién es mi líder o punto de apoyo.");
    expect(first).toBeChecked();
    expect(second).not.toBeChecked();

    fireEvent.click(second);

    await waitFor(() => {
      expect(api.put).toHaveBeenCalledWith(
        "/training/me/lessons/checklist-1/checklist",
        { completed_items: [0, 1] },
      );
    });
    expect(await screen.findByText("2/2")).toBeInTheDocument();
  });

  it("lets an employee submit a course quiz after completing the lessons", async () => {
    useSession.mockReturnValue({
      principal: {
        profile: { id: "employee-1", first_name: "Ana" },
      },
      hasPermission: (permission) => [
        "training.read",
        "training.consume",
        "training.quiz.take",
      ].includes(permission),
    });

    const quizAssignment = {
      ...assignment,
      course: {
        ...assignment.course,
        has_quiz: true,
        completed_lessons: 1,
        lesson_count: 1,
        progress_percent: 50,
      },
    };
    const quizCourseDetail = {
      ...employeeDetail,
      course: {
        ...employeeDetail.course,
        has_quiz: true,
        completed_lessons: 1,
        lesson_count: 1,
        progress_percent: 50,
        modules: [
          {
            ...employeeDetail.course.modules[0],
            lessons: [
              {
                ...employeeDetail.course.modules[0].lessons[0],
                completed: true,
              },
            ],
          },
        ],
      },
    };
    const quizPayload = {
      id: "quiz-1",
      course_id: "course-1",
      title: "Evaluación final",
      passing_score: 70,
      question_count: 1,
      questions: [
        {
          id: "question-1",
          prompt: "¿Cuál es la opción correcta?",
          options: ["Incorrecta", "Correcta"],
          position: 1,
        },
      ],
      attempts: [],
    };

    api.get.mockImplementation((url) => {
      if (url === "/training/me") {
        return Promise.resolve({ data: { items: [quizAssignment] } });
      }
      if (url === "/training/me/courses/course-1") {
        return Promise.resolve({ data: quizCourseDetail });
      }
      if (url === "/training/me/courses/course-1/quiz") {
        return Promise.resolve({ data: quizPayload });
      }
      return Promise.reject(new Error(`Unexpected GET ${url}`));
    });

    api.post.mockResolvedValueOnce({
      data: {
        attempt: {
          id: "attempt-1",
          attempt_number: 1,
          score_percent: 100,
          passed: true,
        },
        assignment_status: "COMPLETED",
        passing_score: 70,
      },
    });

    renderPage();

    expect(await screen.findByText(/¿Cuál es la opción correcta\?/)).toBeInTheDocument();
    fireEvent.click(screen.getByLabelText("Correcta"));
    fireEvent.click(screen.getByRole("button", { name: "Enviar evaluación" }));

    await waitFor(() => {
      expect(api.post).toHaveBeenCalledWith(
        "/training/me/courses/course-1/quiz/attempts",
        { answers: { "question-1": 1 } },
      );
    });
  });

  it("lets an ADMIN scaffold the ASIATI onboarding journey", async () => {
    useSession.mockReturnValue({
      principal: {
        profile: { id: "admin-1", first_name: "Admin" },
      },
      hasPermission: (permission) => [
        "training.read",
        "training.manage",
        "training.assign",
        "training.results.read",
      ].includes(permission),
    });

    api.get.mockImplementation((url) => {
      if (url === "/training/me") return Promise.resolve({ data: { items: [] } });
      if (url === "/training/courses") return Promise.resolve({ data: { items: [] } });
      if (url === "/employees") return Promise.resolve({ data: { items: [] } });
      return Promise.reject(new Error(`Unexpected GET ${url}`));
    });

    api.post.mockResolvedValueOnce({
      data: {
        id: "preset-1",
        title: "Onboarding ASIATI",
        description: "Ruta corporativa",
        is_onboarding: true,
        status: "DRAFT",
        modules: [],
      },
    });

    renderPage();

    fireEvent.click(await screen.findByRole("button", { name: "Crear ruta ASIATI" }));

    await waitFor(() => {
      expect(api.post).toHaveBeenCalledWith(
        "/training/courses/presets/asiati-onboarding",
      );
    });
  });

  it("shows course administration to an ADMIN and creates a course", async () => {
    useSession.mockReturnValue({
      principal: {
        profile: { id: "admin-1", first_name: "Admin" },
      },
      hasPermission: (permission) => [
        "training.read",
        "training.manage",
        "training.assign",
        "training.results.read",
      ].includes(permission),
    });

    const draftCourse = {
      id: "course-1",
      title: "Inducción ASIATI",
      description: "Base",
      status: "DRAFT",
      module_count: 0,
      lesson_count: 0,
      progress_percent: 0,
    };

    api.get.mockImplementation((url) => {
      if (url === "/training/me") {
        return Promise.resolve({ data: { items: [] } });
      }
      if (url === "/training/courses") {
        return Promise.resolve({ data: { items: [draftCourse] } });
      }
      if (url === "/employees") {
        return Promise.resolve({ data: { items: [] } });
      }
      if (url === "/training/courses/course-1") {
        return Promise.resolve({
          data: { ...draftCourse, modules: [] },
        });
      }
      if (url === "/training/courses/course-1/assignments") {
        return Promise.resolve({
          data: {
            items: [
              {
                id: "course-assignment-1",
                status: "ASSIGNED",
                employee: {
                  id: "employee-1",
                  email: "employee@asiati.com.co",
                  first_name: "Ana",
                  last_name: "Pérez",
                  job_title: "Comercial",
                  department: "Ventas",
                },
                course: {
                  ...draftCourse,
                  status: "PUBLISHED",
                  progress_percent: 50,
                },
              },
            ],
          },
        });
      }
      return Promise.reject(new Error(`Unexpected GET ${url}`));
    });

    api.post.mockResolvedValueOnce({
      data: {
        id: "course-2",
        title: "Seguridad",
        description: "Curso interno",
        status: "DRAFT",
        modules: [],
      },
    });

    renderPage();

    expect(await screen.findByRole("button", { name: "+ Crear curso" })).toBeInTheDocument();
    expect((await screen.findAllByText("Inducción ASIATI")).length).toBeGreaterThan(0);
    expect(await screen.findByText("Ana Pérez")).toBeInTheDocument();
    expect(screen.getByText("50%")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "+ Crear curso" }));
    fireEvent.change(screen.getByLabelText("Título"), {
      target: { value: "Seguridad" },
    });
    fireEvent.change(screen.getByLabelText("Descripción"), {
      target: { value: "Curso interno" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Crear curso" }));

    await waitFor(() => {
      expect(api.post).toHaveBeenCalledWith("/training/courses", {
        title: "Seguridad",
        description: "Curso interno",
        is_onboarding: false,
      });
    });
  });
});


describe("Training onboarding classification", () => {
  it("lets any training administrator create an onboarding course", async () => {
    vi.clearAllMocks();
    useSession.mockReturnValue({
      principal: {
        profile: { id: "admin-2", first_name: "Administrador" },
      },
      hasPermission: (permission) => [
        "training.read",
        "training.manage",
        "training.assign",
        "training.results.read",
      ].includes(permission),
    });

    api.get.mockImplementation((url) => {
      if (url === "/training/me") return Promise.resolve({ data: { items: [] } });
      if (url === "/training/courses") return Promise.resolve({ data: { items: [] } });
      if (url === "/employees") return Promise.resolve({ data: { items: [] } });
      return Promise.reject(new Error(`Unexpected GET ${url}`));
    });

    api.post.mockResolvedValueOnce({
      data: {
        id: "onboarding-course",
        title: "Inducción ASIATI",
        description: "Bienvenida",
        is_onboarding: true,
        status: "DRAFT",
        modules: [],
      },
    });

    renderPage();

    fireEvent.click(await screen.findByRole("button", { name: "+ Crear curso" }));
    fireEvent.change(screen.getByLabelText("Título"), {
      target: { value: "Inducción ASIATI" },
    });
    fireEvent.change(screen.getByLabelText("Descripción"), {
      target: { value: "Bienvenida" },
    });
    fireEvent.click(screen.getByRole("checkbox"));
    fireEvent.click(screen.getByRole("button", { name: "Crear curso" }));

    await waitFor(() => {
      expect(api.post).toHaveBeenCalledWith("/training/courses", {
        title: "Inducción ASIATI",
        description: "Bienvenida",
        is_onboarding: true,
      });
    });
  });
});
