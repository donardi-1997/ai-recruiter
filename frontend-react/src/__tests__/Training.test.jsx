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

  it("embeds Google Drive onboarding videos inside the journey", async () => {
    useSession.mockReturnValue({
      principal: {
        profile: { id: "employee-1", first_name: "Ana" },
      },
      hasPermission: (permission) => [
        "training.read",
        "training.consume",
      ].includes(permission),
    });

    const driveAssignment = {
      ...assignment,
      course: {
        ...assignment.course,
        next_lesson_id: "drive-lesson",
      },
    };
    const driveDetail = {
      ...employeeDetail,
      course: {
        ...employeeDetail.course,
        next_lesson_id: "drive-lesson",
        modules: [
          {
            ...employeeDetail.course.modules[0],
            title: "Así trabajamos",
            lessons: [
              {
                ...employeeDetail.course.modules[0].lessons[0],
                id: "drive-lesson",
                title: "Módulo 4 · Permisos y vacaciones",
                video_url: "https://drive.google.com/file/d/1qklJ9U8raurFmxsQMrEL3az_Ez0zpyKs/view?usp=drivesdk",
              },
            ],
          },
        ],
      },
    };

    api.get.mockImplementation((url) => {
      if (url === "/training/me") {
        return Promise.resolve({ data: { items: [driveAssignment] } });
      }
      if (url === "/training/me/courses/course-1") {
        return Promise.resolve({ data: driveDetail });
      }
      return Promise.reject(new Error(`Unexpected GET ${url}`));
    });

    renderPage();

    const player = await screen.findByTitle("Video: Módulo 4 · Permisos y vacaciones");
    expect(player).toHaveAttribute(
      "src",
      "https://drive.google.com/file/d/1qklJ9U8raurFmxsQMrEL3az_Ez0zpyKs/preview",
    );
    expect(
      screen.getByRole("link", { name: /Abrir en Google Drive/i }),
    ).toHaveAttribute(
      "href",
      "https://drive.google.com/file/d/1qklJ9U8raurFmxsQMrEL3az_Ez0zpyKs/view?usp=drivesdk",
    );
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

describe("Focused onboarding sessions", () => {
  it("recommends a short session and keeps non-active modules collapsed", async () => {
    vi.clearAllMocks();
    useSession.mockReturnValue({
      principal: {
        profile: { id: "employee-focus", first_name: "Laura" },
      },
      hasPermission: (permission) => [
        "training.read",
        "training.consume",
      ].includes(permission),
    });

    const focusedAssignment = {
      ...assignment,
      id: "assignment-focus",
      course: {
        ...assignment.course,
        id: "focus-course",
        title: "Onboarding ASIATI",
        lesson_count: 3,
        completed_lessons: 0,
        progress_percent: 0,
        next_lesson_id: "focus-1",
      },
    };

    const focusedDetail = {
      assignment_id: "assignment-focus",
      assignment_status: "ASSIGNED",
      course: {
        ...employeeDetail.course,
        id: "focus-course",
        title: "Onboarding ASIATI",
        lesson_count: 3,
        completed_lessons: 0,
        progress_percent: 0,
        next_lesson_id: "focus-1",
        modules: [
          {
            id: "focus-module-1",
            title: "Primera etapa",
            position: 1,
            lesson_count: 2,
            completed_lessons: 0,
            progress_percent: 0,
            is_complete: false,
            estimated_minutes: 9,
            has_unknown_duration: false,
            lessons: [
              {
                id: "focus-1",
                title: "Bienvenida breve",
                description: "Introducción.",
                content_type: "ARTICLE",
                estimated_minutes: 4,
                is_optional: false,
                completed: false,
                position: 1,
              },
              {
                id: "focus-2",
                title: "Conoce ASIATI",
                description: "Contexto.",
                content_type: "ARTICLE",
                estimated_minutes: 5,
                is_optional: false,
                completed: false,
                position: 2,
              },
              {
                id: "optional-resource",
                title: "Instagram opcional",
                description: "Complementario.",
                content_type: "RESOURCE",
                external_url: "https://example.com",
                estimated_minutes: 2,
                is_optional: true,
                completed: false,
                position: 3,
              },
            ],
          },
          {
            id: "focus-module-2",
            title: "Segundo módulo",
            position: 2,
            lesson_count: 1,
            completed_lessons: 0,
            progress_percent: 0,
            is_complete: false,
            estimated_minutes: 10,
            has_unknown_duration: false,
            lessons: [
              {
                id: "focus-3",
                title: "Módulo largo",
                description: "Siguiente sesión.",
                content_type: "VIDEO",
                estimated_minutes: 10,
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
        return Promise.resolve({ data: { items: [focusedAssignment] } });
      }
      if (url === "/training/me/courses/focus-course") {
        return Promise.resolve({ data: focusedDetail });
      }
      return Promise.reject(new Error(`Unexpected GET ${url}`));
    });

    renderPage();

    expect(await screen.findByText("Sesión recomendada")).toBeInTheDocument();
    expect(screen.getByText("2 actividades para avanzar")).toBeInTheDocument();
    expect(screen.getByText("~9 min")).toBeInTheDocument();
    expect(screen.getAllByText("Bienvenida breve").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Conoce ASIATI").length).toBeGreaterThan(0);

    expect(screen.queryByText("Módulo largo")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /Segundo módulo/i }));
    expect(await screen.findByText("Módulo largo")).toBeInTheDocument();
  });
});

describe("Onboarding quality preview", () => {
  it("shows quality warnings and previews the route for a selected employee", async () => {
    vi.clearAllMocks();
    useSession.mockReturnValue({
      principal: {
        profile: { id: "admin-quality", first_name: "Administrador" },
      },
      hasPermission: (permission) => [
        "training.read",
        "training.manage",
        "training.assign",
        "training.results.read",
      ].includes(permission),
    });

    const adminCourse = {
      id: "quality-course",
      title: "Onboarding ASIATI",
      description: "Ruta corporativa",
      is_onboarding: true,
      status: "DRAFT",
      module_count: 2,
      lesson_count: 2,
      progress_percent: 0,
      modules: [],
      quiz: {
        id: "quiz-quality",
        title: "Evaluación final",
        passing_score: 70,
        question_count: 5,
        questions: [],
      },
      quality: {
        issue_count: 1,
        warning_count: 1,
        info_count: 0,
        known_minutes: 12,
        required_activity_count: 2,
        quiz_question_count: 5,
        issues: [
          {
            severity: "warning",
            code: "LONG_ACTIVITY",
            message: '"Video corporativo" dura ~9 min. Conviene dividirla en bloques de máximo ~7 min.',
            module_id: "module-quality",
            lesson_id: "lesson-quality",
          },
        ],
      },
    };

    const employee = {
      id: "employee-quality",
      email: "laura@asiati.com.co",
      first_name: "Laura",
      last_name: "Pérez",
      job_title: "Comercial",
      department: "Ventas",
    };

    const genericPreview = {
      ...adminCourse,
      preview_employee: null,
      modules: [
        {
          id: "module-common",
          title: "Bienvenida",
          position: 1,
          lesson_count: 1,
          audience_job_title: null,
          audience_department: null,
          lessons: [
            {
              id: "lesson-common",
              title: "Conoce ASIATI",
              content_type: "ARTICLE",
              estimated_minutes: 3,
              is_optional: false,
            },
          ],
        },
        {
          id: "module-dev",
          title: "Desarrollo",
          position: 2,
          lesson_count: 1,
          audience_job_title: "Desarrollador",
          audience_department: null,
          lessons: [
            {
              id: "lesson-dev",
              title: "Git",
              content_type: "ARTICLE",
              estimated_minutes: 3,
              is_optional: false,
            },
          ],
        },
      ],
    };

    const employeePreview = {
      ...genericPreview,
      module_count: 1,
      lesson_count: 1,
      preview_employee: employee,
      modules: [genericPreview.modules[0]],
      quality: {
        ...genericPreview.quality,
        required_activity_count: 1,
        known_minutes: 3,
        issues: [],
        issue_count: 0,
        warning_count: 0,
      },
    };

    api.get.mockImplementation((url, config) => {
      if (url === "/training/me") {
        return Promise.resolve({ data: { items: [] } });
      }
      if (url === "/training/courses") {
        return Promise.resolve({ data: { items: [adminCourse] } });
      }
      if (url === "/employees") {
        return Promise.resolve({ data: { items: [employee] } });
      }
      if (url === "/training/courses/quality-course") {
        return Promise.resolve({ data: adminCourse });
      }
      if (url === "/training/courses/quality-course/assignments") {
        return Promise.resolve({ data: { items: [] } });
      }
      if (url === "/training/courses/quality-course/preview") {
        return Promise.resolve({
          data: config?.params?.employee_id
            ? employeePreview
            : genericPreview,
        });
      }
      return Promise.reject(new Error(`Unexpected GET ${url}`));
    });

    renderPage();

    expect(await screen.findByText("Control de calidad")).toBeInTheDocument();
    expect(screen.getByText("1 por revisar")).toBeInTheDocument();
    expect(screen.getByText("Actividad extensa")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Vista previa" }));

    expect(
      await screen.findByRole("heading", { name: "Así verá la ruta el empleado" }),
    ).toBeInTheDocument();
    expect(screen.getByText("Desarrollo")).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("Previsualizar como"), {
      target: { value: "employee-quality" },
    });

    await waitFor(() => {
      expect(api.get).toHaveBeenCalledWith(
        "/training/courses/quality-course/preview",
        { params: { employee_id: "employee-quality" } },
      );
    });
    expect((await screen.findAllByText("Laura Pérez")).length).toBeGreaterThan(1);
    expect(screen.queryByText("Desarrollo")).not.toBeInTheDocument();
    expect(screen.getByText("Bienvenida")).toBeInTheDocument();
  });
});

