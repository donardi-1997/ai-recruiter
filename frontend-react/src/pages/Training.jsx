// eslint-disable-next-line no-unused-vars
import React from "react";
import { useCallback, useEffect, useMemo, useState } from "react";

import api from "../api/client";
import { useSession } from "../context/SessionContext";


function courseProgress(course) {
  return Number.isFinite(course?.progress_percent) ? course.progress_percent : 0;
}


function isDirectVideo(url) {
  return /\.(mp4|webm|ogg)(\?|#|$)/i.test(String(url || ""));
}


function googleDrivePreviewUrl(url) {
  const match = String(url || "").match(
    /^https:\/\/drive\.google\.com\/file\/d\/([^/]+)\//i,
  );
  return match
    ? `https://drive.google.com/file/d/${match[1]}/preview`
    : "";
}


function lessonTypeLabel(type) {
  return {
    VIDEO: "Video",
    ARTICLE: "Lectura",
    RESOURCE: "Recurso",
    CHECKLIST: "Checklist",
  }[String(type || "VIDEO").toUpperCase()] || "Contenido";
}


function lessonTypeIcon(type) {
  return {
    VIDEO: "▶",
    ARTICLE: "▤",
    RESOURCE: "↗",
    CHECKLIST: "✓",
  }[String(type || "VIDEO").toUpperCase()] || "•";
}


function recommendedSession(lessons, nextLessonId) {
  const requiredPending = lessons.filter(
    (lesson) => !lesson.is_optional && !lesson.completed,
  );
  if (requiredPending.length === 0) {
    return { items: [], minutes: 0, hasUnknownDuration: false };
  }

  const startIndex = Math.max(
    0,
    requiredPending.findIndex((lesson) => lesson.id === nextLessonId),
  );
  const queue = requiredPending.slice(startIndex);
  const items = [];
  let minutes = 0;
  let hasUnknownDuration = false;

  for (const lesson of queue) {
    if (items.length >= 3) break;

    const lessonMinutes = Number(lesson.estimated_minutes);
    const hasKnownMinutes = Number.isFinite(lessonMinutes) && lessonMinutes > 0;

    if (items.length > 0 && hasKnownMinutes && minutes + lessonMinutes > 15) {
      break;
    }

    items.push(lesson);
    if (hasKnownMinutes) {
      minutes += lessonMinutes;
    } else {
      hasUnknownDuration = true;
      break;
    }
  }

  return { items, minutes, hasUnknownDuration };
}


function Training() {
  const { principal, hasPermission } = useSession();
  const canManage = hasPermission("training.manage");
  const canAssign = hasPermission("training.assign");
  const canViewResults = hasPermission("training.results.read");
  const canTakeQuiz = hasPermission("training.quiz.take");
  const firstName = principal?.profile?.first_name || "equipo";

  const [myAssignments, setMyAssignments] = useState([]);
  const [courses, setCourses] = useState([]);
  const [employees, setEmployees] = useState([]);
  const [selectedCourseId, setSelectedCourseId] = useState("");
  const [selectedCourse, setSelectedCourse] = useState(null);
  const [courseAssignments, setCourseAssignments] = useState([]);
  const [selectedAssignmentId, setSelectedAssignmentId] = useState("");
  const [employeeCourse, setEmployeeCourse] = useState(null);
  const [loading, setLoading] = useState(true);
  const [detailLoading, setDetailLoading] = useState(false);
  const [error, setError] = useState("");
  const [creatingCourse, setCreatingCourse] = useState(false);
  const [saving, setSaving] = useState(false);
  const [uploadingLessonId, setUploadingLessonId] = useState("");
  const [courseForm, setCourseForm] = useState({
    title: "",
    description: "",
    is_onboarding: false,
  });
  const [moduleForm, setModuleForm] = useState({
    title: "",
    description: "",
    audience_job_title: "",
    audience_department: "",
  });
  const [lessonForms, setLessonForms] = useState({});
  const [assignEmployeeId, setAssignEmployeeId] = useState("");
  const [quizForm, setQuizForm] = useState({
    title: "Evaluación final",
    passing_score: "70",
  });
  const [questionForm, setQuestionForm] = useState({
    prompt: "",
    options: ["", "", "", ""],
    correct_option: "0",
  });
  const [employeeQuiz, setEmployeeQuiz] = useState(null);
  const [quizAnswers, setQuizAnswers] = useState({});
  const [quizResult, setQuizResult] = useState(null);
  const [activeLessonId, setActiveLessonId] = useState("");
  const [creatingPreset, setCreatingPreset] = useState(false);
  const [checklistSavingLessonId, setChecklistSavingLessonId] = useState("");
  const [expandedModuleIds, setExpandedModuleIds] = useState([]);
  const [previewOpen, setPreviewOpen] = useState(false);
  const [previewEmployeeId, setPreviewEmployeeId] = useState("");
  const [previewData, setPreviewData] = useState(null);
  const [previewLoading, setPreviewLoading] = useState(false);

  const loadHome = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const requests = [api.get("/training/me")];
      if (canManage) requests.push(api.get("/training/courses"));
      if (canAssign) requests.push(api.get("/employees"));

      const responses = await Promise.all(requests);
      const myItems = Array.isArray(responses[0]?.data?.items)
        ? responses[0].data.items
        : [];
      setMyAssignments(myItems);

      let index = 1;
      if (canManage) {
        const managedItems = Array.isArray(responses[index]?.data?.items)
          ? responses[index].data.items
          : [];
        setCourses(managedItems);
        setSelectedCourseId((current) => {
          if (current && managedItems.some((item) => item.id === current)) return current;
          return managedItems[0]?.id || "";
        });
        index += 1;
      }
      if (canAssign) {
        const employeeItems = Array.isArray(responses[index]?.data?.items)
          ? responses[index].data.items
          : [];
        setEmployees(employeeItems);
      }

      setSelectedAssignmentId((current) => {
        if (current && myItems.some((item) => item.id === current)) return current;
        return myItems[0]?.id || "";
      });
    } catch (err) {
      setError(err.response?.data?.detail || "No fue posible cargar la capacitación.");
    } finally {
      setLoading(false);
    }
  }, [canAssign, canManage]);

  const loadAdminCourse = useCallback(async (courseId) => {
    if (!canManage || !courseId) {
      setSelectedCourse(null);
      setCourseAssignments([]);
      return;
    }
    setDetailLoading(true);
    try {
      const requests = [api.get(`/training/courses/${courseId}`)];
      if (canViewResults) {
        requests.push(api.get(`/training/courses/${courseId}/assignments`));
      }
      const [courseResponse, assignmentsResponse] = await Promise.all(requests);
      setSelectedCourse(courseResponse.data);
      setCourseAssignments(
        canViewResults && Array.isArray(assignmentsResponse?.data?.items)
          ? assignmentsResponse.data.items
          : [],
      );
    } catch (err) {
      setError(err.response?.data?.detail || "No fue posible cargar el curso.");
    } finally {
      setDetailLoading(false);
    }
  }, [canManage, canViewResults]);

  const selectedAssignment = useMemo(
    () => myAssignments.find((assignment) => assignment.id === selectedAssignmentId),
    [myAssignments, selectedAssignmentId],
  );

  const journeyLessons = useMemo(
    () => (
      employeeCourse?.course?.modules || []
    ).flatMap((module) => (
      module.lessons || []
    ).map((lesson) => ({ ...lesson, module }))),
    [employeeCourse],
  );

  const activeJourneyLesson = useMemo(
    () => journeyLessons.find((lesson) => lesson.id === activeLessonId) || null,
    [activeLessonId, journeyLessons],
  );

  const activeJourneyIndex = useMemo(
    () => journeyLessons.findIndex((lesson) => lesson.id === activeLessonId),
    [activeLessonId, journeyLessons],
  );

  const previousJourneyLesson = activeJourneyIndex > 0
    ? journeyLessons[activeJourneyIndex - 1]
    : null;
  const nextJourneyLesson = activeJourneyIndex >= 0
    ? journeyLessons[activeJourneyIndex + 1] || null
    : null;

  const nextRequiredJourneyLesson = useMemo(
    () => journeyLessons.find(
      (lesson) => lesson.id === employeeCourse?.course?.next_lesson_id,
    ) || null,
    [employeeCourse?.course?.next_lesson_id, journeyLessons],
  );

  const currentRecommendedSession = useMemo(
    () => recommendedSession(
      journeyLessons,
      employeeCourse?.course?.next_lesson_id,
    ),
    [employeeCourse?.course?.next_lesson_id, journeyLessons],
  );

  const activeModuleId = activeJourneyLesson?.module?.id || "";

  function toggleJourneyModule(moduleId) {
    setExpandedModuleIds((current) => (
      current.includes(moduleId)
        ? current.filter((id) => id !== moduleId)
        : [...current, moduleId]
    ));
  }

  function openFinalQuiz() {
    document.getElementById("training-final-quiz")?.scrollIntoView({
      behavior: "smooth",
      block: "start",
    });
  }

  const loadEmployeeCourse = useCallback(async (courseId) => {
    if (!courseId) {
      setEmployeeCourse(null);
      setEmployeeQuiz(null);
      return;
    }
    setDetailLoading(true);
    try {
      const { data } = await api.get(`/training/me/courses/${courseId}`);
      setEmployeeCourse(data);
      setActiveLessonId((current) => (
        current && (data.course?.modules || []).some((module) => (
          (module.lessons || []).some((lesson) => lesson.id === current)
        ))
          ? current
          : data.course?.next_lesson_id
            || data.course?.modules?.[0]?.lessons?.[0]?.id
            || ""
      ));
      setQuizResult(null);
      setQuizAnswers({});

      const lessonsComplete = (
        data.course?.lesson_count > 0
        && data.course?.completed_lessons >= data.course?.lesson_count
      );
      if (canTakeQuiz && data.course?.has_quiz && lessonsComplete) {
        const quizResponse = await api.get(`/training/me/courses/${courseId}/quiz`);
        setEmployeeQuiz(quizResponse.data);
      } else {
        setEmployeeQuiz(null);
      }
    } catch (err) {
      setError(err.response?.data?.detail || "No fue posible abrir el curso.");
    } finally {
      setDetailLoading(false);
    }
  }, [canTakeQuiz]);

  useEffect(() => {
    const timeoutId = window.setTimeout(() => {
      void loadHome();
    }, 0);
    return () => window.clearTimeout(timeoutId);
  }, [loadHome]);

  useEffect(() => {
    if (!selectedCourseId) return undefined;
    const timeoutId = window.setTimeout(() => {
      void loadAdminCourse(selectedCourseId);
    }, 0);
    return () => window.clearTimeout(timeoutId);
  }, [loadAdminCourse, selectedCourseId]);

  useEffect(() => {
    const courseId = selectedAssignment?.course?.id;
    if (!courseId) return undefined;
    const timeoutId = window.setTimeout(() => {
      void loadEmployeeCourse(courseId);
    }, 0);
    return () => window.clearTimeout(timeoutId);
  }, [loadEmployeeCourse, selectedAssignment]);

  async function loadCoursePreview(employeeId = "") {
    if (!selectedCourseId) return;
    setPreviewLoading(true);
    setError("");
    try {
      const config = employeeId
        ? { params: { employee_id: employeeId } }
        : undefined;
      const { data } = await api.get(
        `/training/courses/${selectedCourseId}/preview`,
        config,
      );
      setPreviewData(data);
    } catch (err) {
      setError(err.response?.data?.detail || "No fue posible generar la vista previa.");
    } finally {
      setPreviewLoading(false);
    }
  }

  async function openCoursePreview() {
    setPreviewOpen(true);
    setPreviewEmployeeId("");
    setPreviewData(null);
    await loadCoursePreview("");
  }

  async function changePreviewEmployee(employeeId) {
    setPreviewEmployeeId(employeeId);
    await loadCoursePreview(employeeId);
  }

  function closeCoursePreview() {
    if (previewLoading) return;
    setPreviewOpen(false);
    setPreviewEmployeeId("");
    setPreviewData(null);
  }

  async function createCourse(event) {
    event.preventDefault();
    setSaving(true);
    setError("");
    try {
      const { data } = await api.post("/training/courses", {
        title: courseForm.title.trim(),
        description: courseForm.description.trim() || null,
        is_onboarding: courseForm.is_onboarding,
      });
      setCourseForm({ title: "", description: "", is_onboarding: false });
      setCreatingCourse(false);
      await loadHome();
      setSelectedCourseId(data.id);
    } catch (err) {
      setError(err.response?.data?.detail || "No fue posible crear el curso.");
    } finally {
      setSaving(false);
    }
  }

  async function createAsiatiPreset() {
    setCreatingPreset(true);
    setError("");
    try {
      const { data } = await api.post("/training/courses/presets/asiati-onboarding");
      await loadHome();
      setSelectedCourseId(data.id);
      setSelectedCourse(data);
    } catch (err) {
      setError(err.response?.data?.detail || "No fue posible crear la ruta ASIATI.");
    } finally {
      setCreatingPreset(false);
    }
  }

  async function publishCourse() {
    if (!selectedCourseId) return;
    setSaving(true);
    setError("");
    try {
      const { data } = await api.put(`/training/courses/${selectedCourseId}`, {
        status: "PUBLISHED",
      });
      setSelectedCourse(data);
      await loadHome();
    } catch (err) {
      setError(err.response?.data?.detail || "No fue posible publicar el curso.");
    } finally {
      setSaving(false);
    }
  }

  async function addModule(event) {
    event.preventDefault();
    if (!selectedCourseId) return;
    setSaving(true);
    setError("");
    try {
      const { data } = await api.post(
        `/training/courses/${selectedCourseId}/modules`,
        {
          title: moduleForm.title.trim(),
          description: moduleForm.description.trim() || null,
          audience_job_title: moduleForm.audience_job_title.trim() || null,
          audience_department: moduleForm.audience_department.trim() || null,
        },
      );
      setSelectedCourse(data);
      setModuleForm({
        title: "",
        description: "",
        audience_job_title: "",
        audience_department: "",
      });
      await loadHome();
    } catch (err) {
      setError(err.response?.data?.detail || "No fue posible agregar el módulo.");
    } finally {
      setSaving(false);
    }
  }

  function lessonForm(moduleId) {
    return lessonForms[moduleId] || {
      title: "",
      description: "",
      video_url: "",
      duration_seconds: "",
      content_type: "VIDEO",
      external_url: "",
      estimated_minutes: "",
      checklist_items: "",
      is_optional: false,
    };
  }

  function updateLessonForm(moduleId, patch) {
    setLessonForms((current) => ({
      ...current,
      [moduleId]: {
        ...(current[moduleId] || {
          title: "",
          description: "",
          video_url: "",
          duration_seconds: "",
          content_type: "VIDEO",
          external_url: "",
          estimated_minutes: "",
          is_optional: false,
        }),
        ...patch,
      },
    }));
  }

  async function addLesson(event, moduleId) {
    event.preventDefault();
    const form = lessonForm(moduleId);
    setSaving(true);
    setError("");
    try {
      const duration = form.duration_seconds
        ? Number.parseInt(form.duration_seconds, 10)
        : null;
      const estimatedMinutes = form.estimated_minutes
        ? Number.parseInt(form.estimated_minutes, 10)
        : null;
      const { data } = await api.post(`/training/modules/${moduleId}/lessons`, {
        title: form.title.trim(),
        description: form.description.trim() || null,
        video_url: form.video_url.trim() || null,
        duration_seconds: Number.isInteger(duration) ? duration : null,
        content_type: form.content_type,
        external_url: form.external_url.trim() || null,
        estimated_minutes: Number.isInteger(estimatedMinutes) ? estimatedMinutes : null,
        checklist_items: form.content_type === "CHECKLIST"
          ? form.checklist_items
              .split("\n")
              .map((item) => item.trim())
              .filter(Boolean)
          : [],
        is_optional: Boolean(form.is_optional),
      });
      setSelectedCourse(data);
      setLessonForms((current) => ({
        ...current,
        [moduleId]: {
          title: "",
          description: "",
          video_url: "",
          duration_seconds: "",
          content_type: "VIDEO",
          external_url: "",
          estimated_minutes: "",
          is_optional: false,
        },
      }));
      await loadHome();
    } catch (err) {
      setError(err.response?.data?.detail || "No fue posible agregar la lección.");
    } finally {
      setSaving(false);
    }
  }

  async function uploadLessonVideo(lessonId, file) {
    if (!file) return;
    const allowedTypes = ["video/mp4", "video/webm", "video/ogg"];
    if (!allowedTypes.includes(file.type)) {
      setError("Formato no soportado. Usa MP4, WebM u OGG.");
      return;
    }
    if (file.size <= 0 || file.size > 1024 * 1024 * 1024) {
      setError("El video debe pesar como máximo 1 GB.");
      return;
    }

    setUploadingLessonId(lessonId);
    setError("");
    try {
      const manifest = {
        filename: file.name,
        content_type: file.type,
        size_bytes: file.size,
      };
      const { data } = await api.post(
        `/training/lessons/${lessonId}/video/upload`,
        manifest,
      );

      const formData = new FormData();
      Object.entries(data.upload.fields || {}).forEach(([key, value]) => {
        formData.append(key, value);
      });
      formData.append("file", file);

      const uploadResponse = await fetch(data.upload.url, {
        method: "POST",
        body: formData,
      });
      if (!uploadResponse.ok) {
        throw new Error("S3 upload failed");
      }

      const finalized = await api.post(
        `/training/lessons/${lessonId}/video/complete`,
        {
          key: data.key,
          content_type: file.type,
          size_bytes: file.size,
        },
      );
      setSelectedCourse(finalized.data);
      await loadHome();
    } catch (err) {
      setError(
        err.response?.data?.detail
          || "No fue posible subir el video. Intenta nuevamente.",
      );
    } finally {
      setUploadingLessonId("");
    }
  }

  async function assignCourse(event) {
    event.preventDefault();
    if (!selectedCourseId || !assignEmployeeId) return;
    setSaving(true);
    setError("");
    try {
      await api.post(
        `/training/courses/${selectedCourseId}/assignments/${assignEmployeeId}`,
      );
      setAssignEmployeeId("");
      await loadAdminCourse(selectedCourseId);
    } catch (err) {
      setError(err.response?.data?.detail || "No fue posible asignar el curso.");
    } finally {
      setSaving(false);
    }
  }

  async function completeLesson(lessonId) {
    setSaving(true);
    setError("");
    try {
      const { data } = await api.post(
        `/training/me/lessons/${lessonId}/complete`,
      );
      const nextRequiredId = data.course?.next_lesson_id || "";
      setEmployeeCourse(data);
      await Promise.all([
        loadHome(),
        loadEmployeeCourse(data.course.id),
      ]);
      if (nextRequiredId) setActiveLessonId(nextRequiredId);
    } catch (err) {
      setError(err.response?.data?.detail || "No fue posible guardar el avance.");
    } finally {
      setSaving(false);
    }
  }

  async function updateChecklistItem(lesson, index, checked) {
    if (!lesson?.id) return;
    const current = new Set(lesson.checklist_completed_items || []);
    if (checked) current.add(index);
    else current.delete(index);
    const completedItems = Array.from(current).sort((a, b) => a - b);
    const willComplete = completedItems.length === (lesson.checklist_items || []).length;
    const currentIndex = journeyLessons.findIndex((item) => item.id === lesson.id);
    const nextId = currentIndex >= 0
      ? journeyLessons[currentIndex + 1]?.id || ""
      : "";

    setChecklistSavingLessonId(lesson.id);
    setError("");
    try {
      const { data } = await api.put(
        `/training/me/lessons/${lesson.id}/checklist`,
        { completed_items: completedItems },
      );
      setEmployeeCourse(data);
      await Promise.all([
        loadHome(),
        loadEmployeeCourse(data.course.id),
      ]);
      if (willComplete && nextId) setActiveLessonId(nextId);
    } catch (err) {
      setError(
        err.response?.data?.detail ||
        "No fue posible guardar el avance del checklist.",
      );
    } finally {
      setChecklistSavingLessonId("");
    }
  }

  async function createQuiz(event) {
    event.preventDefault();
    if (!selectedCourseId) return;
    setSaving(true);
    setError("");
    try {
      await api.post(`/training/courses/${selectedCourseId}/quiz`, {
        title: quizForm.title.trim(),
        passing_score: Number.parseInt(quizForm.passing_score, 10),
      });
      await loadAdminCourse(selectedCourseId);
    } catch (err) {
      setError(err.response?.data?.detail || "No fue posible crear la evaluación.");
    } finally {
      setSaving(false);
    }
  }

  function updateQuestionOption(index, value) {
    setQuestionForm((current) => ({
      ...current,
      options: current.options.map((option, optionIndex) => (
        optionIndex === index ? value : option
      )),
    }));
  }

  async function addQuizQuestion(event) {
    event.preventDefault();
    const quizId = selectedCourse?.quiz?.id;
    if (!quizId) return;
    setSaving(true);
    setError("");
    try {
      await api.post(`/training/quizzes/${quizId}/questions`, {
        prompt: questionForm.prompt.trim(),
        options: questionForm.options.map((option) => option.trim()),
        correct_option: Number.parseInt(questionForm.correct_option, 10),
      });
      setQuestionForm({
        prompt: "",
        options: ["", "", "", ""],
        correct_option: "0",
      });
      await loadAdminCourse(selectedCourseId);
    } catch (err) {
      setError(err.response?.data?.detail || "No fue posible agregar la pregunta.");
    } finally {
      setSaving(false);
    }
  }

  async function submitQuiz(event) {
    event.preventDefault();
    const courseId = employeeCourse?.course?.id;
    if (!courseId || !employeeQuiz) return;
    setSaving(true);
    setError("");
    try {
      const { data } = await api.post(
        `/training/me/courses/${courseId}/quiz/attempts`,
        { answers: quizAnswers },
      );
      setQuizResult(data);
      await Promise.all([
        loadHome(),
        loadEmployeeCourse(courseId),
      ]);
      setQuizResult(data);
    } catch (err) {
      setError(err.response?.data?.detail || "No fue posible enviar la evaluación.");
    } finally {
      setSaving(false);
    }
  }

  if (loading) {
    return (
      <div className="page">
        <div className="page-loading"><span /> Preparando capacitación…</div>
      </div>
    );
  }

  return (
    <div className="page training-page">
      <header className="page-header split-header">
        <div>
          <span className="eyebrow">Aprendizaje interno</span>
          <h1>Capacitación</h1>
          <p>Hola, {firstName}. Cursos, videos y progreso en un solo lugar.</p>
        </div>
        {canManage && (
          <div className="training-header-actions">
            <button
              className="btn btn-secondary"
              type="button"
              onClick={createAsiatiPreset}
              disabled={creatingPreset}
            >
              {creatingPreset ? "Preparando…" : "Crear ruta ASIATI"}
            </button>
            <button
              className="btn btn-primary"
              type="button"
              onClick={() => setCreatingCourse(true)}
            >
              + Crear curso
            </button>
          </div>
        )}
      </header>

      {error && <div className="alert" role="alert">{error}</div>}

      {canManage && (
        <section className="training-admin-layout">
          <aside className="panel training-course-sidebar">
            <div className="panel-heading">
              <div>
                <span className="eyebrow">Administración</span>
                <h2>Cursos</h2>
              </div>
              <span className="training-count">{courses.length}</span>
            </div>

            {courses.length === 0 ? (
              <div className="empty-state compact">
                <strong>Aún no hay cursos</strong>
                <p>Crea el primer curso de inducción o capacitación.</p>
              </div>
            ) : (
              <div className="training-course-list">
                {courses.map((course) => (
                  <button
                    className={`training-course-row ${course.id === selectedCourseId ? "active" : ""}`}
                    key={course.id}
                    type="button"
                    onClick={() => setSelectedCourseId(course.id)}
                  >
                    <span>
                      <strong>{course.title}</strong>
                      <small>{course.module_count} módulos · {course.lesson_count} lecciones</small>
                      {course.is_onboarding && <small className="training-onboarding-label">Inducción</small>}
                    </span>
                    <b className={`training-status training-status-${course.status.toLowerCase()}`}>
                      {course.status === "PUBLISHED" ? "Publicado" : course.status === "ARCHIVED" ? "Archivado" : "Borrador"}
                    </b>
                  </button>
                ))}
              </div>
            )}
          </aside>

          <div className="training-admin-content">
            {detailLoading && !selectedCourse ? (
              <section className="panel page-loading"><span /> Cargando curso…</section>
            ) : selectedCourse ? (
              <>
                <section className="panel training-course-overview">
                  <div>
                    <span className="eyebrow">Editor de curso</span>
                    <h2>{selectedCourse.title}</h2>
                    <p>{selectedCourse.description || "Sin descripción."}</p>
                    {selectedCourse.is_onboarding && (
                      <span className="training-onboarding-badge">Curso de inducción</span>
                    )}
                  </div>
                  <div className="training-course-overview-actions">
                    <button
                      className="btn btn-secondary"
                      type="button"
                      onClick={openCoursePreview}
                    >
                      Vista previa
                    </button>
                    <span className={`training-status training-status-${String(selectedCourse.status || "DRAFT").toLowerCase()}`}>
                      {selectedCourse.status === "PUBLISHED" ? "Publicado" : selectedCourse.status === "ARCHIVED" ? "Archivado" : "Borrador"}
                    </span>
                    {selectedCourse.status === "DRAFT" && (
                      <button
                        className="btn btn-primary"
                        type="button"
                        onClick={publishCourse}
                        disabled={saving}
                      >
                        Publicar curso
                      </button>
                    )}
                  </div>
                </section>

                {selectedCourse.quality && (
                  <section className="panel training-quality-panel">
                    <div className="panel-heading">
                      <div>
                        <span className="eyebrow">Control de calidad</span>
                        <h2>Experiencia de onboarding</h2>
                      </div>
                      <span className={`training-quality-status ${selectedCourse.quality.warning_count ? "has-warnings" : "is-ready"}`}>
                        {selectedCourse.quality.warning_count
                          ? `${selectedCourse.quality.warning_count} por revisar`
                          : "Sin alertas"}
                      </span>
                    </div>

                    <div className="training-quality-summary">
                      <div>
                        <span>Actividades obligatorias</span>
                        <strong>{selectedCourse.quality.required_activity_count}</strong>
                      </div>
                      <div>
                        <span>Tiempo conocido</span>
                        <strong>~{selectedCourse.quality.known_minutes} min</strong>
                      </div>
                      <div>
                        <span>Preguntas de quiz</span>
                        <strong>{selectedCourse.quality.quiz_question_count}</strong>
                      </div>
                    </div>

                    {selectedCourse.quality.issues?.length > 0 ? (
                      <div className="training-quality-issues">
                        {selectedCourse.quality.issues.map((issue, index) => (
                          <div
                            className={`training-quality-issue is-${issue.severity}`}
                            key={`${issue.code}-${issue.lesson_id || issue.module_id || index}`}
                          >
                            <span aria-hidden="true">
                              {issue.severity === "warning" ? "!" : "i"}
                            </span>
                            <div>
                              <strong>{issue.code === "LONG_ACTIVITY" ? "Actividad extensa" : issue.code === "UNKNOWN_DURATION" ? "Duración pendiente" : issue.code === "MISSING_VIDEO" ? "Video pendiente" : issue.code === "LONG_JOURNEY" ? "Ruta extensa" : issue.code === "MISSING_QUIZ" ? "Evaluación pendiente" : "Sugerencia"}</strong>
                              <p>{issue.message}</p>
                            </div>
                          </div>
                        ))}
                      </div>
                    ) : (
                      <div className="training-quality-ready">
                        La ruta mantiene una estructura ligera con los datos configurados actualmente.
                      </div>
                    )}
                  </section>
                )}

                <section className="panel">
                  <div className="panel-heading">
                    <div>
                      <span className="eyebrow">Contenido</span>
                      <h2>Módulos y lecciones</h2>
                    </div>
                  </div>

                  <div className="training-module-list">
                    {selectedCourse.modules?.map((module) => (
                      <article className="training-module-card" key={module.id}>
                        <div className="training-module-header">
                          <div>
                            <span>Módulo {module.position}</span>
                            <h3>{module.title}</h3>
                            {module.description && <p>{module.description}</p>}
                            {(module.audience_job_title || module.audience_department) && (
                              <small className="training-audience-badge">
                                Solo para: {module.audience_job_title || "cualquier cargo"}
                                {module.audience_department ? ` · ${module.audience_department}` : ""}
                              </small>
                            )}
                          </div>
                          <strong>{module.lessons?.length || 0} lecciones</strong>
                        </div>

                        <div className="training-lesson-list">
                          {module.lessons?.map((lesson) => (
                            <div className="training-lesson-row training-lesson-admin-row" key={lesson.id}>
                              <span className="training-play" aria-hidden="true">{lessonTypeIcon(lesson.content_type)}</span>
                              <div className="training-lesson-admin-copy">
                                <strong>{lesson.title}</strong>
                                <small>
                                  {lessonTypeLabel(lesson.content_type)}
                                  {lesson.estimated_minutes ? ` · ~${lesson.estimated_minutes} min` : ""}
                                  {lesson.is_optional ? " · opcional" : ""}
                                </small>
                                {lesson.video_url && (
                                  <small>
                                    {lesson.video_source === "managed"
                                      ? "Video privado en S3"
                                      : "Video por URL externa"}
                                  </small>
                                )}
                                {lesson.external_url && <small>Recurso externo configurado</small>}
                            {lesson.content_type === "CHECKLIST" && lesson.checklist_items?.length > 0 && (
                              <small>{lesson.checklist_items.length} puntos de checklist</small>
                            )}
                                {lesson.video_size_bytes ? (
                                  <small>{Math.max(1, Math.round(lesson.video_size_bytes / (1024 * 1024)))} MB</small>
                                ) : null}
                              </div>
                              {selectedCourse.status === "DRAFT" && (
                                <label className={`training-video-upload-button ${uploadingLessonId === lesson.id ? "is-uploading" : ""}`}>
                                  <span>
                                    {uploadingLessonId === lesson.id
                                      ? "Subiendo…"
                                      : lesson.video_url
                                        ? "Reemplazar video"
                                        : "Subir video"}
                                  </span>
                                  <input
                                    type="file"
                                    accept="video/mp4,video/webm,video/ogg"
                                    disabled={Boolean(uploadingLessonId)}
                                    onChange={(event) => {
                                      const file = event.target.files?.[0];
                                      event.target.value = "";
                                      void uploadLessonVideo(lesson.id, file);
                                    }}
                                  />
                                </label>
                              )}
                            </div>
                          ))}
                        </div>

                        {selectedCourse.status === "DRAFT" && (
                          <form className="training-inline-form" onSubmit={(event) => addLesson(event, module.id)}>
                            <strong>Nueva lección</strong>
                            <input
                              aria-label={`Título de lección para ${module.title}`}
                              placeholder="Título de la lección"
                              value={lessonForm(module.id).title}
                              onChange={(event) => updateLessonForm(module.id, { title: event.target.value })}
                              required
                            />
                            <textarea
                              aria-label={`Descripción de lección para ${module.title}`}
                              placeholder="Descripción breve"
                              value={lessonForm(module.id).description}
                              onChange={(event) => updateLessonForm(module.id, { description: event.target.value })}
                              rows="2"
                            />
                            <div className="training-inline-grid training-content-type-grid">
                              <select
                                aria-label={`Tipo de contenido para ${module.title}`}
                                value={lessonForm(module.id).content_type}
                                onChange={(event) => updateLessonForm(module.id, { content_type: event.target.value })}
                              >
                                <option value="VIDEO">Video</option>
                                <option value="ARTICLE">Lectura</option>
                                <option value="RESOURCE">Recurso externo</option>
                                <option value="CHECKLIST">Checklist</option>
                              </select>
                              <input
                                aria-label={`Tiempo estimado para ${module.title}`}
                                type="number"
                                min="1"
                                max="1440"
                                placeholder="Tiempo estimado (min)"
                                value={lessonForm(module.id).estimated_minutes}
                                onChange={(event) => updateLessonForm(module.id, { estimated_minutes: event.target.value })}
                              />
                            </div>
                            {lessonForm(module.id).content_type === "VIDEO" && (
                              <div className="training-inline-grid">
                                <input
                                  aria-label={`URL de video para ${module.title}`}
                                  type="url"
                                  placeholder="https://.../video.mp4"
                                  value={lessonForm(module.id).video_url}
                                  onChange={(event) => updateLessonForm(module.id, { video_url: event.target.value })}
                                />
                                <input
                                  aria-label={`Duración de lección para ${module.title}`}
                                  type="number"
                                  min="1"
                                  placeholder="Duración (segundos)"
                                  value={lessonForm(module.id).duration_seconds}
                                  onChange={(event) => updateLessonForm(module.id, { duration_seconds: event.target.value })}
                                />
                              </div>
                            )}
                            {lessonForm(module.id).content_type === "RESOURCE" && (
                              <input
                                aria-label={`URL de recurso para ${module.title}`}
                                type="url"
                                placeholder="https://..."
                                value={lessonForm(module.id).external_url}
                                onChange={(event) => updateLessonForm(module.id, { external_url: event.target.value })}
                                required
                              />
                            )}
                            {lessonForm(module.id).content_type === "CHECKLIST" && (
                              <textarea
                                aria-label={`Puntos de checklist para ${module.title}`}
                                placeholder={"Un punto por línea\nEj. Tengo acceso al correo\nSé quién es mi líder"}
                                value={lessonForm(module.id).checklist_items}
                                onChange={(event) => updateLessonForm(module.id, { checklist_items: event.target.value })}
                                rows="5"
                              />
                            )}
                            <label className="training-optional-toggle">
                              <input
                                type="checkbox"
                                checked={lessonForm(module.id).is_optional}
                                onChange={(event) => updateLessonForm(module.id, { is_optional: event.target.checked })}
                              />
                              <span>Contenido opcional (no bloquea el avance)</span>
                            </label>
                            <button className="btn btn-secondary" type="submit" disabled={saving}>
                              Agregar lección
                            </button>
                          </form>
                        )}
                      </article>
                    ))}
                  </div>

                  {selectedCourse.status === "DRAFT" && (
                    <form className="training-module-form" onSubmit={addModule}>
                      <span className="eyebrow">Nuevo módulo</span>
                      <div className="training-inline-grid">
                        <input
                          aria-label="Título del módulo"
                          placeholder="Ej. Bienvenida a ASIATI"
                          value={moduleForm.title}
                          onChange={(event) => setModuleForm({ ...moduleForm, title: event.target.value })}
                          required
                        />
                        <input
                          aria-label="Descripción del módulo"
                          placeholder="Descripción breve"
                          value={moduleForm.description}
                          onChange={(event) => setModuleForm({ ...moduleForm, description: event.target.value })}
                        />
                      </div>
                      <div className="training-inline-grid">
                        <input
                          aria-label="Cargo objetivo del módulo"
                          placeholder="Cargo específico (opcional)"
                          value={moduleForm.audience_job_title}
                          onChange={(event) => setModuleForm({ ...moduleForm, audience_job_title: event.target.value })}
                        />
                        <input
                          aria-label="Área objetivo del módulo"
                          placeholder="Área específica (opcional)"
                          value={moduleForm.audience_department}
                          onChange={(event) => setModuleForm({ ...moduleForm, audience_department: event.target.value })}
                        />
                      </div>
                      <p className="training-form-note">
                        Si dejas cargo y área vacíos, el módulo será visible para todos los empleados asignados.
                      </p>
                      <button className="btn btn-secondary" type="submit" disabled={saving}>
                        + Agregar módulo
                      </button>
                    </form>
                  )}
                </section>

                <section className="panel training-quiz-admin">
                  <div className="panel-heading">
                    <div>
                      <span className="eyebrow">Evaluación</span>
                      <h2>Quiz del curso</h2>
                    </div>
                    {selectedCourse.quiz && (
                      <span className="training-status training-status-published">
                        Aprueba con {selectedCourse.quiz.passing_score}%
                      </span>
                    )}
                  </div>

                  {!selectedCourse.quiz ? (
                    selectedCourse.status === "DRAFT" ? (
                      <form className="training-quiz-create-form" onSubmit={createQuiz}>
                        <div className="training-inline-grid">
                          <input
                            aria-label="Título de la evaluación"
                            value={quizForm.title}
                            onChange={(event) => setQuizForm({ ...quizForm, title: event.target.value })}
                            placeholder="Evaluación final"
                            required
                          />
                          <input
                            aria-label="Puntaje mínimo para aprobar"
                            type="number"
                            min="1"
                            max="100"
                            value={quizForm.passing_score}
                            onChange={(event) => setQuizForm({ ...quizForm, passing_score: event.target.value })}
                            required
                          />
                        </div>
                        <button className="btn btn-secondary" type="submit" disabled={saving}>
                          + Crear evaluación
                        </button>
                      </form>
                    ) : (
                      <div className="empty-state compact">
                        <strong>Curso sin evaluación</strong>
                        <p>Este curso se completa únicamente con sus lecciones.</p>
                      </div>
                    )
                  ) : (
                    <div className="training-quiz-admin-body">
                      <div className="training-quiz-summary">
                        <div>
                          <strong>{selectedCourse.quiz.title}</strong>
                          <small>{selectedCourse.quiz.question_count} preguntas · mínimo {selectedCourse.quiz.passing_score}%</small>
                        </div>
                      </div>

                      {selectedCourse.quiz.questions?.length > 0 && (
                        <div className="training-quiz-question-list">
                          {selectedCourse.quiz.questions.map((question) => (
                            <article className="training-quiz-question-admin" key={question.id}>
                              <span>{question.position}</span>
                              <div>
                                <strong>{question.prompt}</strong>
                                <ol type="A">
                                  {question.options.map((option, index) => (
                                    <li className={index === question.correct_option ? "is-correct" : ""} key={option}>
                                      {option}
                                    </li>
                                  ))}
                                </ol>
                              </div>
                            </article>
                          ))}
                        </div>
                      )}

                      {selectedCourse.status === "DRAFT" && (
                        <form className="training-quiz-question-form" onSubmit={addQuizQuestion}>
                          <strong>Nueva pregunta</strong>
                          <textarea
                            aria-label="Pregunta de evaluación"
                            rows="2"
                            value={questionForm.prompt}
                            onChange={(event) => setQuestionForm({ ...questionForm, prompt: event.target.value })}
                            placeholder="Escribe la pregunta"
                            required
                          />
                          <div className="training-quiz-options-grid">
                            {questionForm.options.map((option, index) => (
                              <input
                                key={index}
                                aria-label={`Opción ${index + 1}`}
                                value={option}
                                onChange={(event) => updateQuestionOption(index, event.target.value)}
                                placeholder={`Opción ${index + 1}`}
                                required
                              />
                            ))}
                          </div>
                          <div className="training-quiz-question-actions">
                            <select
                              aria-label="Respuesta correcta"
                              value={questionForm.correct_option}
                              onChange={(event) => setQuestionForm({ ...questionForm, correct_option: event.target.value })}
                            >
                              {questionForm.options.map((_, index) => (
                                <option key={index} value={String(index)}>Correcta: opción {index + 1}</option>
                              ))}
                            </select>
                            <button className="btn btn-secondary" type="submit" disabled={saving}>
                              Agregar pregunta
                            </button>
                          </div>
                        </form>
                      )}
                    </div>
                  )}
                </section>

                {canAssign && (
                  <section className="panel">
                    <div className="panel-heading">
                      <div>
                        <span className="eyebrow">Distribución</span>
                        <h2>Asignar a un empleado</h2>
                      </div>
                    </div>
                    <form className="training-assignment-form" onSubmit={assignCourse}>
                      <select
                        aria-label="Empleado para asignar"
                        value={assignEmployeeId}
                        onChange={(event) => setAssignEmployeeId(event.target.value)}
                        required
                      >
                        <option value="">Selecciona un empleado</option>
                        {employees.map((employee) => (
                          <option key={employee.id} value={employee.id}>
                            {[employee.first_name, employee.last_name].filter(Boolean).join(" ") || employee.email}
                          </option>
                        ))}
                      </select>
                      <button
                        className="btn btn-primary"
                        type="submit"
                        disabled={saving || selectedCourse.status !== "PUBLISHED"}
                      >
                        Asignar curso
                      </button>
                    </form>
                    {selectedCourse.status !== "PUBLISHED" && (
                      <p className="training-form-note">Publica el curso antes de asignarlo.</p>
                    )}

                    {canViewResults && courseAssignments.length > 0 && (
                      <div className="training-results-list">
                        {courseAssignments.map((assignment) => (
                          <div className="training-result-row" key={assignment.id}>
                            <div>
                              <strong>
                                {[assignment.employee.first_name, assignment.employee.last_name].filter(Boolean).join(" ")
                                  || assignment.employee.email}
                              </strong>
                              <small>{assignment.employee.job_title || assignment.employee.department || assignment.employee.email}</small>
                              {assignment.quiz_result && (
                                <small>
                                  Quiz: {assignment.quiz_result.latest_score ?? "—"}%
                                  {assignment.quiz_result.passed ? " · aprobado" : assignment.quiz_result.attempt_count ? " · pendiente" : " · sin intento"}
                                </small>
                              )}
                            </div>
                            <div className="training-result-progress">
                              <span>{assignment.course.progress_percent}%</span>
                              <div><i style={{ width: `${assignment.course.progress_percent}%` }} /></div>
                            </div>
                            <span className="training-status training-status-published">
                              {assignment.status === "COMPLETED" ? "Completado" : "En curso"}
                            </span>
                          </div>
                        ))}
                      </div>
                    )}
                  </section>
                )}
              </>
            ) : (
              <section className="panel empty-state">
                <strong>Selecciona o crea un curso</strong>
                <p>Desde aquí podrás construir sus módulos, videos y asignaciones.</p>
              </section>
            )}
          </div>
        </section>
      )}

      <section className={`training-learning-section ${canManage ? "training-learning-after-admin" : ""}`}>
        <div className="training-section-heading">
          <div>
            <span className="eyebrow">Mi aprendizaje</span>
            <h2>Mis cursos</h2>
          </div>
          <span>{myAssignments.length} asignados</span>
        </div>

        {myAssignments.length === 0 ? (
          <section className="panel empty-state training-empty">
            <span className="training-mark" aria-hidden="true">▶</span>
            <strong>Aún no tienes cursos asignados</strong>
            <p>Cuando se publique una capacitación para tu perfil aparecerá aquí.</p>
          </section>
        ) : (
          <div className="training-learning-layout">
            <aside className="training-assignment-list">
              {myAssignments.map((assignment) => (
                <button
                  key={assignment.id}
                  type="button"
                  className={`training-assignment-card ${assignment.id === selectedAssignmentId ? "active" : ""}`}
                  onClick={() => setSelectedAssignmentId(assignment.id)}
                >
                  <div>
                    <span className="training-status training-status-published">
                      {assignment.status === "COMPLETED" ? "Completado" : "En curso"}
                    </span>
                    <h3>{assignment.course.title}</h3>
                    <p>{assignment.course.description || "Capacitación ASIATI"}</p>
                    {assignment.course.is_onboarding && (
                      <small className="training-onboarding-label">Inducción ASIATI</small>
                    )}
                  </div>
                  <div className="training-progress">
                    <span><strong>{courseProgress(assignment.course)}%</strong> completado</span>
                    <div><i style={{ width: `${courseProgress(assignment.course)}%` }} /></div>
                  </div>
                </button>
              ))}
            </aside>

            <section className="panel training-player-panel">
              {detailLoading && !employeeCourse ? (
                <div className="page-loading"><span /> Cargando contenido…</div>
              ) : employeeCourse?.course ? (
                <>
                  <div className="training-player-heading">
                    <div>
                      <span className="eyebrow">Curso asignado</span>
                      <h2>{employeeCourse.course.title}</h2>
                      <p>{employeeCourse.course.description || "Capacitación ASIATI"}</p>
                    </div>
                    <strong>{employeeCourse.course.progress_percent}%</strong>
                  </div>

                  <div className="training-journey-overview">
                    <div className="training-journey-progress-copy">
                      <span>Tu avance</span>
                      <strong>{employeeCourse.course.progress_percent}%</strong>
                      <small>
                        {employeeCourse.course.completed_lessons} de {employeeCourse.course.lesson_count} actividades obligatorias
                        {employeeCourse.course.remaining_minutes
                          ? ` · ~${employeeCourse.course.remaining_minutes} min restantes`
                          : ""}
                        {employeeCourse.course.has_unknown_remaining_duration
                          ? " + contenido con duración por confirmar"
                          : ""}
                      </small>
                    </div>
                    <div className="training-journey-progress-bar">
                      <i style={{ width: `${employeeCourse.course.progress_percent}%` }} />
                    </div>
                  </div>

                  <section className="training-focus-session">
                    <div className="training-focus-session-copy">
                      <span className="eyebrow">Sesión recomendada</span>
                      <h3>
                        {currentRecommendedSession.items.length > 0
                          ? `${currentRecommendedSession.items.length} actividad${currentRecommendedSession.items.length === 1 ? "" : "es"} para avanzar`
                          : employeeCourse.course.has_quiz && !selectedAssignment?.quiz_result?.passed
                            ? "Ya puedes presentar la evaluación"
                            : "Ruta de contenido completada"}
                      </h3>
                      <p>
                        {currentRecommendedSession.items.length > 0
                          ? "Avanza en un bloque corto. Tu progreso queda guardado automáticamente."
                          : employeeCourse.course.has_quiz && !selectedAssignment?.quiz_result?.passed
                            ? "Terminaste el contenido obligatorio. Solo falta el quiz final."
                            : "Completaste las actividades obligatorias de esta ruta."}
                      </p>
                    </div>

                    {currentRecommendedSession.items.length > 0 && (
                      <div className="training-focus-session-items">
                        {currentRecommendedSession.items.map((lesson) => (
                          <span key={lesson.id}>
                            {lessonTypeIcon(lesson.content_type)} {lesson.title}
                          </span>
                        ))}
                      </div>
                    )}

                    <div className="training-focus-session-actions">
                      {currentRecommendedSession.items.length > 0 && (
                        <span className="training-focus-session-time">
                          {currentRecommendedSession.minutes > 0
                            ? `~${currentRecommendedSession.minutes} min`
                            : "Duración por confirmar"}
                          {currentRecommendedSession.hasUnknownDuration
                            && currentRecommendedSession.minutes > 0
                            ? " + contenido por confirmar"
                            : ""}
                        </span>
                      )}
                      {currentRecommendedSession.items.length > 0 ? (
                        <button
                          className="btn btn-primary"
                          type="button"
                          onClick={() => setActiveLessonId(currentRecommendedSession.items[0].id)}
                        >
                          Continuar ahora →
                        </button>
                      ) : employeeCourse.course.has_quiz && !selectedAssignment?.quiz_result?.passed ? (
                        <button
                          className="btn btn-primary"
                          type="button"
                          onClick={openFinalQuiz}
                        >
                          Ir a evaluación final →
                        </button>
                      ) : null}
                    </div>
                  </section>

                  <div className="training-journey-layout">
                    <aside className="training-journey-steps" aria-label="Ruta del curso">
                      {employeeCourse.course.modules?.map((module) => (
                        <section
                          className={`training-journey-module ${module.is_complete ? "is-complete" : ""}`}
                          key={module.id}
                        >
                          <button
                            className="training-journey-module-heading"
                            type="button"
                            aria-expanded={expandedModuleIds.includes(module.id) || activeModuleId === module.id}
                            onClick={() => toggleJourneyModule(module.id)}
                          >
                            <span>{module.is_complete ? "✓" : module.position}</span>
                            <div>
                              <strong>{module.title}</strong>
                              <small>
                                {module.completed_lessons}/{module.lesson_count}
                                {module.has_unknown_duration
                                  ? ` · ~${module.estimated_minutes} min + contenido por confirmar`
                                  : ` · ~${module.estimated_minutes} min`}
                              </small>
                            </div>
                            <i aria-hidden="true">
                              {expandedModuleIds.includes(module.id) || activeModuleId === module.id ? "−" : "+"}
                            </i>
                          </button>
                          {(expandedModuleIds.includes(module.id) || activeModuleId === module.id) && (
                            <div className="training-journey-lessons">
                              {module.lessons?.map((lesson) => (
                                <button
                                  key={lesson.id}
                                  type="button"
                                  className={`training-journey-lesson-button ${lesson.id === activeLessonId ? "active" : ""} ${lesson.completed ? "is-complete" : ""}`}
                                  onClick={() => setActiveLessonId(lesson.id)}
                                >
                                  <span>{lesson.completed ? "✓" : lessonTypeIcon(lesson.content_type)}</span>
                                  <div>
                                    <strong>{lesson.title}</strong>
                                    <small>
                                      {lessonTypeLabel(lesson.content_type)}
                                      {lesson.estimated_minutes
                                        ? ` · ~${lesson.estimated_minutes} min`
                                        : " · duración por confirmar"}
                                      {lesson.is_optional ? " · opcional" : ""}
                                    </small>
                                  </div>
                                </button>
                              ))}
                            </div>
                          )}
                        </section>
                      ))}
                      {employeeCourse.course.has_quiz && (
                        <button
                          type="button"
                          className={`training-journey-quiz-step ${selectedAssignment?.quiz_result?.passed ? "is-complete" : ""}`}
                          onClick={openFinalQuiz}
                        >
                          <span>{selectedAssignment?.quiz_result?.passed ? "✓" : "?"}</span>
                          <div>
                            <strong>Evaluación final</strong>
                            <small>
                              {employeeCourse.course.completed_lessons < employeeCourse.course.lesson_count
                                ? "Se habilita al completar la ruta"
                                : selectedAssignment?.quiz_result?.passed
                                  ? "Aprobada"
                                  : "Lista para presentar"}
                            </small>
                          </div>
                        </button>
                      )}
                    </aside>

                    <article className="training-journey-focus">
                      {activeJourneyLesson ? (
                        <>
                          <div className="training-journey-focus-meta">
                            <span>{activeJourneyLesson.module.title}</span>
                            <b>
                              {lessonTypeLabel(activeJourneyLesson.content_type)}
                              {activeJourneyLesson.estimated_minutes
                                ? ` · ~${activeJourneyLesson.estimated_minutes} min`
                                : " · duración por confirmar"}
                            </b>
                          </div>
                          <h3>{activeJourneyLesson.title}</h3>
                          {activeJourneyLesson.description && (
                            <p className="training-journey-description">{activeJourneyLesson.description}</p>
                          )}

                          {activeJourneyLesson.video_url && (
                            <div className="training-video training-journey-video">
                              {isDirectVideo(activeJourneyLesson.video_url) ? (
                                <video controls preload="metadata">
                                  <source src={activeJourneyLesson.video_url} />
                                  Tu navegador no puede reproducir este video.
                                </video>
                              ) : googleDrivePreviewUrl(activeJourneyLesson.video_url) ? (
                                <>
                                  <iframe
                                    className="training-drive-player"
                                    src={googleDrivePreviewUrl(activeJourneyLesson.video_url)}
                                    title={`Video: ${activeJourneyLesson.title}`}
                                    allow="autoplay; encrypted-media"
                                    allowFullScreen
                                  />
                                  <a
                                    className="training-drive-fallback"
                                    href={activeJourneyLesson.video_url}
                                    target="_blank"
                                    rel="noreferrer"
                                  >
                                    ¿No carga el video? Abrir en Google Drive ↗
                                  </a>
                                </>
                              ) : (
                                <a
                                  className="btn btn-ghost"
                                  href={activeJourneyLesson.video_url}
                                  target="_blank"
                                  rel="noreferrer"
                                >
                                  Abrir video ↗
                                </a>
                              )}
                            </div>
                          )}

                          {activeJourneyLesson.external_url && (
                            <a
                              className="training-resource-card"
                              href={activeJourneyLesson.external_url}
                              target="_blank"
                              rel="noreferrer"
                            >
                              <span>↗</span>
                              <div>
                                <strong>Abrir recurso</strong>
                                <small>Se abrirá en una pestaña nueva.</small>
                              </div>
                            </a>
                          )}

                          {activeJourneyLesson.content_type === "CHECKLIST" && (
                            activeJourneyLesson.checklist_items?.length > 0 ? (
                              <div className="training-checklist-card training-checklist-items">
                                <div className="training-checklist-heading">
                                  <strong>Tus primeros pasos</strong>
                                  <span>
                                    {(activeJourneyLesson.checklist_completed_items || []).length}
                                    /{activeJourneyLesson.checklist_items.length}
                                  </span>
                                </div>
                                {activeJourneyLesson.checklist_items.map((item, index) => {
                                  const checked = (activeJourneyLesson.checklist_completed_items || []).includes(index);
                                  return (
                                    <label className={checked ? "is-checked" : ""} key={item}>
                                      <input
                                        type="checkbox"
                                        checked={checked}
                                        disabled={activeJourneyLesson.completed || checklistSavingLessonId === activeJourneyLesson.id}
                                        onChange={(event) => {
                                          void updateChecklistItem(
                                            activeJourneyLesson,
                                            index,
                                            event.target.checked,
                                          );
                                        }}
                                      />
                                      <span>{item}</span>
                                    </label>
                                  );
                                })}
                                <small>
                                  El avance se guarda automáticamente. Puedes salir y continuar después.
                                </small>
                              </div>
                            ) : (
                              <div className="training-checklist-card">
                                <strong>Antes de continuar</strong>
                                <span>Confirma que revisaste los puntos de esta actividad con tu líder o responsable.</span>
                              </div>
                            )
                          )}

                          <div className="training-journey-actions">
                            <button
                              className="btn btn-secondary"
                              type="button"
                              disabled={!previousJourneyLesson}
                              onClick={() => previousJourneyLesson && setActiveLessonId(previousJourneyLesson.id)}
                            >
                              ← Anterior
                            </button>
                            <div>
                              {activeJourneyLesson.completed ? (
                                <span className="status-pill"><i /> Completada</span>
                              ) : (
                                activeJourneyLesson.content_type === "CHECKLIST"
                                && activeJourneyLesson.checklist_items?.length > 0
                              ) ? (
                                <span className="training-checklist-progress-label">
                                  Completa todos los puntos para continuar
                                </span>
                              ) : (
                                <button
                                  className="btn btn-primary"
                                  type="button"
                                  onClick={() => completeLesson(activeJourneyLesson.id)}
                                  disabled={saving}
                                >
                                  {saving
                                    ? "Guardando…"
                                    : nextJourneyLesson
                                      ? "Completar y continuar →"
                                      : "Marcar completada"}
                                </button>
                              )}
                              {activeJourneyLesson.completed && nextRequiredJourneyLesson && (
                                <button
                                  className="btn btn-primary"
                                  type="button"
                                  onClick={() => setActiveLessonId(nextRequiredJourneyLesson.id)}
                                >
                                  Continuar →
                                </button>
                              )}
                              {activeJourneyLesson.completed
                                && !nextRequiredJourneyLesson
                                && employeeCourse.course.has_quiz
                                && !selectedAssignment?.quiz_result?.passed && (
                                  <button
                                    className="btn btn-primary"
                                    type="button"
                                    onClick={openFinalQuiz}
                                  >
                                    Ir a evaluación final →
                                  </button>
                                )}
                            </div>
                          </div>
                        </>
                      ) : (
                        <div className="empty-state compact">
                          <strong>Ruta lista</strong>
                          <p>No hay más actividades para mostrar.</p>
                        </div>
                      )}
                    </article>
                  </div>

                  {employeeCourse.course.has_quiz && (
                    <section className="training-quiz-employee" id="training-final-quiz">
                      <div className="training-quiz-employee-heading">
                        <div>
                          <span className="eyebrow">Evaluación final</span>
                          <h3>{employeeQuiz?.title || "Quiz del curso"}</h3>
                        </div>
                        {employeeQuiz && (
                          <span className="training-status training-status-published">
                            Mínimo {employeeQuiz.passing_score}%
                          </span>
                        )}
                      </div>

                      {employeeCourse.course.completed_lessons < employeeCourse.course.lesson_count ? (
                        <div className="training-quiz-lock">
                          <strong>Completa todas las lecciones para habilitar la evaluación.</strong>
                        </div>
                      ) : employeeQuiz ? (
                        <form className="training-quiz-attempt-form" onSubmit={submitQuiz}>
                          {employeeQuiz.attempts?.length > 0 && (
                            <div className="training-quiz-attempt-history">
                              <span>Intentos anteriores</span>
                              {employeeQuiz.attempts.map((attempt) => (
                                <b className={attempt.passed ? "score-positive" : "score-negative"} key={attempt.id}>
                                  #{attempt.attempt_number}: {attempt.score_percent}% {attempt.passed ? "✓" : ""}
                                </b>
                              ))}
                            </div>
                          )}

                          {employeeQuiz.questions.map((question, questionIndex) => (
                            <fieldset className="training-quiz-question" key={question.id}>
                              <legend>{questionIndex + 1}. {question.prompt}</legend>
                              {question.options.map((option, optionIndex) => (
                                <label key={option}>
                                  <input
                                    type="radio"
                                    name={`quiz-${question.id}`}
                                    value={optionIndex}
                                    checked={quizAnswers[question.id] === optionIndex}
                                    onChange={() => setQuizAnswers((current) => ({
                                      ...current,
                                      [question.id]: optionIndex,
                                    }))}
                                    required
                                  />
                                  <span>{option}</span>
                                </label>
                              ))}
                            </fieldset>
                          ))}

                          {quizResult?.attempt && (
                            <div className={`training-quiz-result ${quizResult.attempt.passed ? "is-pass" : "is-fail"}`}>
                              <strong>{quizResult.attempt.score_percent}%</strong>
                              <span>
                                {quizResult.attempt.passed
                                  ? "Evaluación aprobada. Curso completado."
                                  : `Aún no alcanzas el ${quizResult.passing_score}%. Puedes intentarlo de nuevo.`}
                              </span>
                            </div>
                          )}

                          <button
                            className="btn btn-primary"
                            type="submit"
                            disabled={saving || Object.keys(quizAnswers).length !== employeeQuiz.question_count}
                          >
                            {saving ? "Enviando…" : "Enviar evaluación"}
                          </button>
                        </form>
                      ) : (
                        <div className="page-loading compact-loading"><span /> Preparando evaluación…</div>
                      )}
                    </section>
                  )}
                </>
              ) : (
                <div className="empty-state">
                  <strong>Selecciona un curso</strong>
                  <p>Abre una capacitación para ver sus módulos y lecciones.</p>
                </div>
              )}
            </section>
          </div>
        )}
      </section>

      {previewOpen && (
        <div className="modal-overlay" role="presentation" onMouseDown={closeCoursePreview}>
          <section
            className="modal training-preview-modal"
            role="dialog"
            aria-modal="true"
            aria-labelledby="training-preview-title"
            onMouseDown={(event) => event.stopPropagation()}
          >
            <div className="modal-header">
              <div>
                <span className="eyebrow">Vista previa</span>
                <h2 id="training-preview-title">Así verá la ruta el empleado</h2>
                <p>La vista respeta los módulos configurados por cargo y área.</p>
              </div>
              <button
                className="btn-close"
                type="button"
                aria-label="Cerrar vista previa"
                onClick={closeCoursePreview}
                disabled={previewLoading}
              >
                ×
              </button>
            </div>

            {employees.length > 0 && (
              <div className="form-group">
                <label htmlFor="training-preview-employee">Previsualizar como</label>
                <select
                  id="training-preview-employee"
                  value={previewEmployeeId}
                  onChange={(event) => void changePreviewEmployee(event.target.value)}
                  disabled={previewLoading}
                >
                  <option value="">Vista general</option>
                  {employees.map((employee) => (
                    <option key={employee.id} value={employee.id}>
                      {[employee.first_name, employee.last_name].filter(Boolean).join(" ") || employee.email}
                      {employee.job_title ? ` · ${employee.job_title}` : ""}
                    </option>
                  ))}
                </select>
              </div>
            )}

            {previewLoading ? (
              <div className="page-loading compact-loading"><span /> Preparando vista previa…</div>
            ) : previewData ? (
              <div className="training-preview-body">
                {previewData.preview_employee && (
                  <div className="training-preview-person">
                    <strong>
                      {[previewData.preview_employee.first_name, previewData.preview_employee.last_name].filter(Boolean).join(" ")
                        || previewData.preview_employee.email}
                    </strong>
                    <span>
                      {[previewData.preview_employee.job_title, previewData.preview_employee.department].filter(Boolean).join(" · ")}
                    </span>
                  </div>
                )}

                <div className="training-preview-summary">
                  <div>
                    <span>Etapas visibles</span>
                    <strong>{previewData.module_count}</strong>
                  </div>
                  <div>
                    <span>Actividades</span>
                    <strong>{previewData.lesson_count}</strong>
                  </div>
                  <div>
                    <span>Tiempo conocido</span>
                    <strong>~{previewData.quality?.known_minutes ?? previewData.estimated_minutes ?? 0} min</strong>
                  </div>
                </div>

                <div className="training-preview-route">
                  {previewData.modules?.map((module) => (
                    <article key={module.id}>
                      <div>
                        <span>{module.position}</span>
                        <div>
                          <strong>{module.title}</strong>
                          <small>
                            {module.lesson_count} obligatorias
                            {module.audience_job_title ? ` · ${module.audience_job_title}` : ""}
                            {module.audience_department ? ` · ${module.audience_department}` : ""}
                          </small>
                        </div>
                      </div>
                      <ul>
                        {module.lessons?.map((lesson) => (
                          <li key={lesson.id}>
                            <span>{lessonTypeIcon(lesson.content_type)}</span>
                            <div>
                              <strong>{lesson.title}</strong>
                              <small>
                                {lessonTypeLabel(lesson.content_type)}
                                {lesson.estimated_minutes ? ` · ~${lesson.estimated_minutes} min` : " · duración por confirmar"}
                                {lesson.is_optional ? " · opcional" : ""}
                              </small>
                            </div>
                          </li>
                        ))}
                      </ul>
                    </article>
                  ))}
                </div>

                {previewData.has_quiz && (
                  <div className="training-preview-quiz">
                    <span>?</span>
                    <div>
                      <strong>Evaluación final</strong>
                      <small>{previewData.quality?.quiz_question_count || 0} preguntas</small>
                    </div>
                  </div>
                )}
              </div>
            ) : null}
          </section>
        </div>
      )}

      {creatingCourse && (
        <div className="modal-overlay" role="presentation" onMouseDown={() => setCreatingCourse(false)}>
          <section className="modal training-course-modal" role="dialog" aria-modal="true" aria-labelledby="create-course-title" onMouseDown={(event) => event.stopPropagation()}>
            <div className="modal-header">
              <div>
                <span className="eyebrow">Nuevo contenido</span>
                <h2 id="create-course-title">Crear curso</h2>
                <p>Comienza con la información general. Después podrás agregar módulos y videos.</p>
              </div>
              <button className="btn-close" type="button" aria-label="Cerrar" onClick={() => setCreatingCourse(false)}>×</button>
            </div>
            <form onSubmit={createCourse}>
              <div className="form-group">
                <label htmlFor="training-course-title">Título</label>
                <input
                  id="training-course-title"
                  value={courseForm.title}
                  onChange={(event) => setCourseForm({ ...courseForm, title: event.target.value })}
                  placeholder="Ej. Inducción ASIATI"
                  required
                />
              </div>
              <div className="form-group">
                <label htmlFor="training-course-description">Descripción</label>
                <textarea
                  id="training-course-description"
                  rows="4"
                  value={courseForm.description}
                  onChange={(event) => setCourseForm({ ...courseForm, description: event.target.value })}
                  placeholder="Objetivo y contexto del curso"
                />
              </div>
              <label className="training-onboarding-toggle">
                <input
                  type="checkbox"
                  checked={courseForm.is_onboarding}
                  onChange={(event) => setCourseForm({ ...courseForm, is_onboarding: event.target.checked })}
                />
                <span>
                  <strong>Curso de inducción</strong>
                  <small>Al asignarlo, el empleado entrará automáticamente en onboarding.</small>
                </span>
              </label>
              <div className="form-actions">
                <button className="btn btn-secondary" type="button" onClick={() => setCreatingCourse(false)}>Cancelar</button>
                <button className="btn btn-primary" type="submit" disabled={saving}>{saving ? "Creando…" : "Crear curso"}</button>
              </div>
            </form>
          </section>
        </div>
      )}
    </div>
  );
}

export default Training;
