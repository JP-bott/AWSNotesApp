
from __future__ import annotations

import argparse
import json
import os
import sys
import uuid
from datetime import datetime, timezone
from typing import Dict, Optional, List

try:
    import boto3
    from botocore.exceptions import BotoCoreError, ClientError
except Exception:
    boto3 = None

try:
    from flask import Flask, request, redirect, url_for, render_template
except Exception:
    Flask = None


DEFAULT_TABLE = os.getenv("NOTES_TABLE_NAME", "Notes_Table")


def now_iso() -> str:
    # UTC timestamp without microseconds
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


class StorageError(Exception):
    pass


class DynamoNotes:
    def __init__(self, table_name: str = DEFAULT_TABLE, key_name: Optional[str] = None, sort_key_name: Optional[str] = None):
        if boto3 is None:
            raise StorageError("boto3 is not installed. Install requirements.txt and try again.")
        self.dynamodb = boto3.resource("dynamodb")
        self.table = self.dynamodb.Table(table_name)
        # prefer provided key names, otherwise try to detect from the table
        self.key_name = key_name or "id"
        self.sort_key_name = sort_key_name
        try:
            ks = getattr(self.table, "key_schema", None)
            if not ks:
                desc = self.table.meta.client.describe_table(TableName=table_name)
                ks = desc.get("Table", {}).get("KeySchema")
            if ks:
                for entry in ks:
                    if entry.get("KeyType") == "HASH":
                        self.key_name = entry.get("AttributeName", self.key_name)
                    elif entry.get("KeyType") == "RANGE" and not self.sort_key_name:
                        self.sort_key_name = entry.get("AttributeName")
        except Exception:
            # fall back to provided/default names
            pass

    def create(self, title: str, content: str, user_id: Optional[str] = None, item_id: Optional[str] = None) -> Dict:
        # client can provide item_id for idempotent creates
        item_id = item_id or str(uuid.uuid4())
        ts = now_iso()
        item = {
            self.key_name: item_id,
            "title": title,
            "content": content,
            "created_at": ts,
            "updated_at": ts,
        }
        if self.sort_key_name:
            if not user_id:
                raise StorageError(f"Table requires sort key '{self.sort_key_name}'; provide user_id")
            item[self.sort_key_name] = user_id
        try:
            # put_item overwrites an item with the same key
            self.table.put_item(Item=item)
            return item
        except (BotoCoreError, ClientError) as e:
            raise StorageError(str(e)) from e

    def get(self, item_id: str, user_id: Optional[str] = None) -> Optional[Dict]:
        try:
            if self.sort_key_name:
                if user_id is None:
                    raise StorageError(f"Table has sort key '{self.sort_key_name}'; provide --user-id to identify the item")
                key = {self.key_name: item_id, self.sort_key_name: user_id}
            else:
                key = {self.key_name: item_id}
            resp = self.table.get_item(Key=key)
            return resp.get("Item")
        except (BotoCoreError, ClientError) as e:
            raise StorageError(str(e)) from e

    def list(self, user_id: Optional[str] = None) -> List[Dict]:
        try:
            if user_id and self.sort_key_name:
                from boto3.dynamodb.conditions import Attr

                resp = self.table.scan(FilterExpression=Attr(self.sort_key_name).eq(user_id))
            else:
                resp = self.table.scan()
            return resp.get("Items", [])
        except (BotoCoreError, ClientError) as e:
            raise StorageError(str(e)) from e

    def update(self, item_id: str, title: Optional[str], content: Optional[str], user_id: Optional[str] = None) -> Dict:
        if title is None and content is None:
            raise ValueError("At least one of title or content must be provided for update")
        expr_vals = {":u": now_iso()}
        update_expr = "SET updated_at = :u"
        if title is not None:
            update_expr += ", title = :t"
            expr_vals[":t"] = title
        if content is not None:
            update_expr += ", content = :c"
            expr_vals[":c"] = content
        try:
            if self.sort_key_name:
                if user_id is None:
                    raise StorageError(f"Table has sort key '{self.sort_key_name}'; provide --user-id to update the item")
                key = {self.key_name: item_id, self.sort_key_name: user_id}
            else:
                key = {self.key_name: item_id}
            resp = self.table.update_item(
                Key=key,
                UpdateExpression=update_expr,
                ExpressionAttributeValues=expr_vals,
                ReturnValues="ALL_NEW",
            )
            return resp.get("Attributes", {})
        except (BotoCoreError, ClientError) as e:
            raise StorageError(str(e)) from e

    def delete(self, item_id: str, user_id: Optional[str] = None) -> None:
        try:
            if self.sort_key_name:
                if user_id is None:
                    raise StorageError(f"Table has sort key '{self.sort_key_name}'; provide --user-id to delete the item")
                key = {self.key_name: item_id, self.sort_key_name: user_id}
            else:
                key = {self.key_name: item_id}
            self.table.delete_item(Key=key)
        except (BotoCoreError, ClientError) as e:
            raise StorageError(str(e)) from e


def get_store(args: argparse.Namespace):
    key_name = getattr(args, "key_name", None)
    sort_key = getattr(args, "sort_key", None)
    # Always use DynamoDB as the sole storage backend. If DynamoDB is not
    # available the DynamoNotes constructor will raise a StorageError which the
    # caller can handle and report to the user.
    table_name = getattr(args, "table", DEFAULT_TABLE)
    return DynamoNotes(table_name=table_name, key_name=key_name, sort_key_name=sort_key)


def cmd_add(args: argparse.Namespace):
    store = get_store(args)
    # pass user id when table requires sort key
    user_id = getattr(args, "user_id", None)
    client_id = getattr(args, "client_id", None)
    item = store.create(args.title, args.content, user_id=user_id, item_id=client_id)
    print(json.dumps(item, indent=2))


def cmd_get(args: argparse.Namespace):
    store = get_store(args)
    user_id = getattr(args, "user_id", None)
    item = store.get(args.id, user_id=user_id)
    if not item:
        print("Note not found", file=sys.stderr)
        sys.exit(2)
    print(json.dumps(item, indent=2))


def cmd_list(args: argparse.Namespace):
    store = get_store(args)
    user_id = getattr(args, "user_id", None)
    items = store.list(user_id=user_id)
    print(json.dumps(items, indent=2))


def cmd_update(args: argparse.Namespace):
    store = get_store(args)
    user_id = getattr(args, "user_id", None)
    item = store.update(args.id, args.title, args.content, user_id=user_id)
    print(json.dumps(item, indent=2))


def cmd_delete(args: argparse.Namespace):
    store = get_store(args)
    user_id = getattr(args, "user_id", None)
    store.delete(args.id, user_id=user_id)
    print("deleted")


def _make_flask_app(store, default_user_id: Optional[str] = None):
    # use 'templates' directory next to this file
    template_dir = os.path.join(os.path.dirname(__file__), "templates")
    app = Flask(__name__, template_folder=template_dir)

        # template moved to templates/notes.html

    @app.route("/", methods=["GET"])
    def index():
        # Use the default user id if provided when starting the UI
        items = store.list(user_id=default_user_id)
        # Ensure deterministic ordering by created_at
        items = sorted(items, key=lambda x: x.get("created_at", ""), reverse=True)
        return render_template("notes.html", notes=items, key_name=store.key_name, default_user_id=default_user_id)

    @app.route("/add", methods=["POST"])
    def add():
        title = request.form.get("title")
        content = request.form.get("content")
        user_id = request.form.get("user_id") or default_user_id
        client_id = request.form.get("client_id") or None
        if not title or not content:
            return "title and content required", 400
        # pass user_id along; storage will enforce if required by table
        # pass client_id to support idempotent creates (prevents duplicate records)
        store.create(title, content, user_id=user_id, item_id=client_id)
        return redirect(url_for("index"))

    @app.route("/delete", methods=["GET", "POST"])
    def delete():
        if request.method == "GET":
            item_id = request.args.get("id") or request.args.get("item_id")
            user_id = request.args.get("user_id") or default_user_id
        else:
            item_id = request.form.get("id") or request.form.get("item_id")
            user_id = request.form.get("user_id") or default_user_id

        if not item_id:
            return "id required", 400
        try:
            store.delete(item_id, user_id=user_id)
        except StorageError as e:
            # simple error page
            return f"delete failed: {e}", 500
        return redirect(url_for("index"))

    @app.route("/edit", methods=["GET", "POST"])
    def edit():
        if request.method == "GET":
            item_id = request.args.get("id") or request.args.get("item_id")
            user_id = request.args.get("user_id") or default_user_id
            if not item_id:
                return "id required", 400
            try:
                item = store.get(item_id, user_id=user_id)
            except StorageError as e:
                return f"fetch failed: {e}", 500
            if not item:
                return "not found", 404
            return render_template("edit.html", item=item, key_name=store.key_name, default_user_id=default_user_id or user_id)

        # POST -> perform update
        item_id = request.form.get("id") or request.form.get("item_id")
        user_id = request.form.get("user_id") or default_user_id
        title = request.form.get("title")
        content = request.form.get("content")
        if not item_id:
            return "id required", 400
        try:
            store.update(item_id, title, content, user_id=user_id)
        except StorageError as e:
            return f"update failed: {e}", 500
        return redirect(url_for("index"))

    return app


def cmd_ui(args: argparse.Namespace):
    if Flask is None:
        print("flask not installed. Install requirements.txt to use the web UI.", file=sys.stderr)
        return 2
    store = get_store(args)
    app = _make_flask_app(store, default_user_id=getattr(args, "user_id", None))
    # Run flask app
    app.run(host=args.host, port=args.port)


# cmd_sync removed — this project no longer supports syncing from a local JSON file


def build_parser() -> argparse.ArgumentParser:
    # common parent parser so options can appear before OR after the subcommand
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--table", default=DEFAULT_TABLE, help="DynamoDB table name (default from env or Notes_Table)")
    common.add_argument("--key-name", help="Partition key attribute name for the table (default: detect or 'id')")
    common.add_argument("--sort-key", help="Sort key (range) attribute name for the table, if any")
    common.add_argument("--user-id", help="User id value to use for operations on tables with sort keys (maps to --sort-key)")

    p = argparse.ArgumentParser(prog="NoteApp.py", description="Notes CRUD against DynamoDB Notes_Table", parents=[common])
    sub = p.add_subparsers(dest="cmd")

    a = sub.add_parser("add", parents=[common])
    a.add_argument("--title", required=True)
    a.add_argument("--content", required=True)
    a.add_argument("--client-id", help="Optional client-generated idempotency id to avoid duplicate creates")
    a.set_defaults(func=cmd_add)

    g = sub.add_parser("get")
    g.add_argument("--id", required=True)
    g.set_defaults(func=cmd_get)

    l = sub.add_parser("list", parents=[common])
    l.set_defaults(func=cmd_list)

    u = sub.add_parser("update", parents=[common])
    u.add_argument("--id", required=True)
    u.add_argument("--title")
    u.add_argument("--content")
    u.set_defaults(func=cmd_update)

    d = sub.add_parser("delete", parents=[common])
    d.add_argument("--id", required=True)
    d.set_defaults(func=cmd_delete)

    ui = sub.add_parser("ui", parents=[common], help="Start a simple web UI for adding and listing notes")
    ui.add_argument("--host", default="127.0.0.1", help="Host to bind the web UI")
    ui.add_argument("--port", type=int, default=5000, help="Port to bind the web UI")
    ui.set_defaults(func=cmd_ui)

    # sync/local-storage support removed

    return p


def main(argv=None):
    argv = argv or sys.argv[1:]
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "func", None):
        parser.print_help()
        return 1

    try:
        args.func(args)
    except StorageError as e:
        print("Storage error:", e, file=sys.stderr)
        return 3
    except Exception as e:
        print("Error:", e, file=sys.stderr)
        return 4
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
