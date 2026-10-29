import { ReactNode, useEffect, useState } from "react";
import { Pressable, ScrollView, StyleSheet, Text, TextInput, View } from "react-native";
import { ApiClient, ApiError } from "../core/api";
import { NAME_RE } from "../core/commands";
import { Json } from "../core/events";
import { storyNote } from "../core/session";
import { Button } from "./controls";
import { color, font, radius, space } from "./theme";

export type DialogSpec =
  | { kind: "confirm"; message: string; yes: string }
  | { kind: "save"; suggested: string }
  | { kind: "load"; dirty: boolean }
  | { kind: "new"; dirty: boolean };

export type DialogResult = boolean | string | "save" | "discard" | null;

function Frame({ title, children, onCancel }: { title: string; children: ReactNode; onCancel: () => void }) {
  return (
    <Pressable style={styles.backdrop} onPress={onCancel} testID="dialog-backdrop">
      <Pressable style={styles.box} onPress={() => undefined} testID="dialog">
        <Text style={styles.title}>{title}</Text>
        {children}
      </Pressable>
    </Pressable>
  );
}

function Buttons({ children }: { children: ReactNode }) {
  return <View style={styles.buttons}>{children}</View>;
}

function describe(h: Json): string {
  const when = String(h.saved_at ?? "").slice(0, 16).replace("T", " ");
  const note = storyNote(h.story as Json | undefined);
  return `${h.name}   ${h.message_count ?? "?"} msgs   ${when}${note ? "   " + note : ""}`;
}

function useSaves(api: ApiClient) {
  const [saves, setSaves] = useState<Json[] | null>(null);
  const [error, setError] = useState("");
  const reload = () =>
    api
      .listHistories()
      .then((s) => {
        setSaves(s);
        setError("");
      })
      .catch((e) => setError(e instanceof ApiError ? e.message : String(e)));
  useEffect(() => {
    void reload();
  }, []);
  return { saves, error, reload };
}

function SaveDialog({ api, suggested, done }: { api: ApiClient; suggested: string; done: (r: DialogResult) => void }) {
  const [name, setName] = useState(suggested);
  const { saves } = useSaves(api);
  const valid = NAME_RE.test(name);
  return (
    <Frame title="Save game" onCancel={() => done(null)}>
      <Text style={styles.dim}>Name</Text>
      <TextInput testID="save-name" value={name} onChangeText={setName} style={styles.input} autoFocus autoCapitalize="none" onSubmitEditing={() => valid && done(name)} />
      {!valid ? <Text style={styles.warn}>Use letters, digits, - and _ (up to 64).</Text> : null}
      <Text style={[styles.dim, { marginTop: space.md }]}>Existing saves</Text>
      <ScrollView style={styles.list}>
        {saves === null ? <Text style={styles.dim}>Loading…</Text> : saves.length === 0 ? <Text style={styles.dim}>No saved games yet.</Text> : null}
        {(saves ?? []).map((h) => (
          <Pressable key={String(h.name)} onPress={() => setName(String(h.name))}>
            <Text style={styles.row}>{describe(h)}</Text>
          </Pressable>
        ))}
      </ScrollView>
      <Buttons>
        <Button label="Cancel" onPress={() => done(null)} testID="dialog-cancel" />
        <Button label="Save" kind="primary" disabled={!valid} onPress={() => done(name)} testID="dialog-ok" />
      </Buttons>
    </Frame>
  );
}

function LoadDialog({ api, dirty, done }: { api: ApiClient; dirty: boolean; done: (r: DialogResult) => void }) {
  const { saves, error, reload } = useSaves(api);
  const [pick, setPick] = useState<string | null>(null);
  const [preview, setPreview] = useState("");
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [problem, setProblem] = useState("");

  useEffect(() => {
    setConfirmDelete(false);
    setPreview("");
    if (!pick) return;
    let live = true;
    api
      .historyInfo(pick)
      .then((i) => live && setPreview(String(i.last_message_preview ?? "")))
      .catch(() => undefined);
    return () => {
      live = false;
    };
  }, [pick]);

  useEffect(() => {
    if (saves && saves.length && !pick) setPick(String(saves[0].name));
  }, [saves]);

  const remove = async () => {
    if (!pick) return;
    try {
      await api.delete(pick);
      setPick(null);
      await reload();
    } catch (e) {
      setProblem(e instanceof ApiError ? e.message : String(e));
    }
  };

  return (
    <Frame title="Load game" onCancel={() => done(null)}>
      {error ? <Text style={styles.warn}>{error}</Text> : null}
      <ScrollView style={styles.list}>
        {saves === null && !error ? <Text style={styles.dim}>Loading…</Text> : null}
        {saves && saves.length === 0 ? <Text style={styles.dim}>No saved games yet.</Text> : null}
        {(saves ?? []).map((h) => (
          <Pressable key={String(h.name)} onPress={() => setPick(String(h.name))} testID={`save-${h.name}`}>
            <Text style={[styles.row, pick === h.name && styles.rowOn]}>{describe(h)}</Text>
          </Pressable>
        ))}
      </ScrollView>
      {preview ? <Text style={[styles.dim, { marginTop: space.sm }]} numberOfLines={3}>{`Preview: "${preview}"`}</Text> : null}
      {dirty ? <Text style={styles.warn}>⚠ Unsaved changes in the current game will be lost.</Text> : null}
      {problem ? <Text style={styles.warn}>{problem}</Text> : null}
      <Buttons>
        <Button label="Cancel" onPress={() => done(null)} testID="dialog-cancel" />
        {confirmDelete ? (
          <>
            <Button label="Really delete" kind="danger" onPress={() => void remove()} testID="delete-confirm" />
            <Button label="Keep" onPress={() => setConfirmDelete(false)} />
          </>
        ) : (
          <Button label="Delete" kind="danger" disabled={!pick} onPress={() => setConfirmDelete(true)} testID="delete" />
        )}
        <Button label="Load" kind="primary" disabled={!pick} onPress={() => pick && done(pick)} testID="dialog-ok" />
      </Buttons>
    </Frame>
  );
}

export function DialogHost({ api, spec, done }: { api: ApiClient; spec: DialogSpec | null; done: (r: DialogResult) => void }) {
  if (!spec) return null;
  switch (spec.kind) {
    case "confirm":
      return (
        <Frame title="Please confirm" onCancel={() => done(false)}>
          <Text style={styles.message}>{spec.message}</Text>
          <Buttons>
            <Button label="Cancel" onPress={() => done(false)} testID="dialog-cancel" />
            <Button label={spec.yes} kind="primary" onPress={() => done(true)} testID="dialog-ok" />
          </Buttons>
        </Frame>
      );
    case "save":
      return <SaveDialog api={api} suggested={spec.suggested} done={done} />;
    case "load":
      return <LoadDialog api={api} dirty={spec.dirty} done={done} />;
    case "new":
      return (
        <Frame title="New game" onCancel={() => done(null)}>
          <Text style={styles.message}>
            {spec.dirty ? "Start a new game? The current game has unsaved changes." : "Start a new game?"}
          </Text>
          <Buttons>
            <Button label="Cancel" onPress={() => done(null)} testID="dialog-cancel" />
            {spec.dirty ? <Button label="Save first…" onPress={() => done("save")} testID="new-save" /> : null}
            <Button label={spec.dirty ? "Discard" : "Start new game"} kind="primary" onPress={() => done("discard")} testID="dialog-ok" />
          </Buttons>
        </Frame>
      );
  }
}

const styles = StyleSheet.create({
  backdrop: { position: "absolute", top: 0, left: 0, right: 0, bottom: 0, backgroundColor: "rgba(0,0,0,0.6)", alignItems: "center", justifyContent: "center", padding: space.lg, zIndex: 100 },
  box: { width: "100%", maxWidth: 560, backgroundColor: color.panel, borderWidth: 1, borderColor: color.accent, borderRadius: radius.md, padding: space.lg },
  title: { color: color.accent, fontFamily: font.story, fontSize: 20, fontWeight: "700", marginBottom: space.md },
  message: { color: color.text, fontFamily: font.ui, fontSize: 15, marginBottom: space.sm },
  dim: { color: color.dim, fontFamily: font.ui, fontSize: 13 },
  warn: { color: color.yellow, fontFamily: font.ui, fontSize: 13, marginTop: space.xs },
  input: { color: color.text, fontFamily: font.ui, fontSize: 15, borderWidth: 1, borderColor: color.border, borderRadius: radius.sm, padding: space.sm, backgroundColor: color.bg },
  list: { maxHeight: 220, marginTop: space.xs },
  row: { color: color.text, fontFamily: font.mono, fontSize: 13, paddingVertical: 5, paddingHorizontal: space.sm },
  rowOn: { backgroundColor: color.panelAlt, color: color.accent },
  buttons: { flexDirection: "row", justifyContent: "flex-end", gap: space.sm, marginTop: space.lg },
});
