import payload from "mzinga";
import { PaginatedDocs } from "mzinga/database";
import { CollectionConfig, TypeWithID } from "mzinga/types";
import { AccessUtils } from "../utils";
import { CollectionUtils } from "../utils/CollectionUtils";
import { MailUtils } from "../utils/MailUtils";
import { MZingaLogger } from "../utils/MZingaLogger";
import { TextUtils } from "../utils/TextUtils";
import { Slugs } from "./Slugs";

const access = new AccessUtils();
const collectionUtils = new CollectionUtils(Slugs.Communications);
const Communications: CollectionConfig = {
  slug: Slugs.Communications,
  access: {
    read: access.GetIsAdmin,
    create: access.GetIsAdmin,
    delete: () => {
      return false;
    },
    update: () => {
      return false;
    },
  },
  admin: {
    ...collectionUtils.GeneratePreviewConfig(),
    useAsTitle: "subject",
    defaultColumns: ["subject", "tos", "status"],
    group: "Notifications",
    disableDuplicate: true,
    enableRichTextRelationship: false,
  },
  hooks: {
    afterChange: [
      async ({ doc }) => {
        const { tos, ccs, bccs, subject, body } = doc;
        // Guard: skip if status was already written by this hook or the worker
        if (doc.status === "pending" || doc.status === "sent") {
          return doc;
        }

        if (process.env.COMMUNICATIONS_EXTERNAL_WORKER === "true") {
          await payload.update({
            collection: Slugs.Communications,
            id: doc.id,
            data: { status: "pending" },
          });
          return doc;
        }

        // Original in-process email sending path
        for (const part of body) {
          if (part.type !== "upload") { continue; }
          const relationToSlug = part.relationTo;
          const uploadDoc = await payload.findByID({
            collection: relationToSlug,
            id: part.value.id,
          });
          part.value = { ...part.value, ...uploadDoc };
        }
        const html = TextUtils.Serialize(body || "");
        try {
          const users = await payload.find({
            collection: tos[0].relationTo,
            where: { id: { in: tos.map((to) => to.value.id || to.value).join(",") } },
          });
          const usersEmails = users.docs.map((u) => u.email);
          if (!usersEmails.length) {
            throw new Error("No valid email addresses found for 'tos' users.");
          }
          let cc;
          if (ccs) {
            const copiedUsers = await payload.find({
              collection: ccs[0].relationTo,
              where: { id: { in: ccs.map((cc) => cc.value.id).join(",") } },
            });
            cc = copiedUsers.docs.map((u) => u.email).join(",");
          }
          let bcc;
          if (bccs) {
            const blindCopiedUsers = await payload.find({
              collection: bccs[0].relationTo,
              where: { id: { in: bccs.map((bcc) => bcc.value.id).join(",") } },
            });
            bcc = blindCopiedUsers.docs.map((u) => u.email).join(",");
          }
          const promises = [];
          for (const to of usersEmails) {
            const message = {
              from: payload.emailOptions.fromAddress,
              subject, to, cc, bcc, html,
            };
            promises.push(
              MailUtils.sendMail(payload, message).catch((e) => {
                MZingaLogger.Instance?.error(`[Communications:err] ${e}`);
                return null;
              }),
            );
          }
          await Promise.all(promises.filter((p) => Boolean(p)));
          await payload.update({
            collection: Slugs.Communications,
            id: doc.id,
            data: { status: "sent" },
          });
          return doc;
        } catch (err) {
          if (err.response?.body?.errors) {
            err.response.body.errors.forEach((error) =>
              MZingaLogger.Instance?.error(
                `[Communications:err] ${error.field} ${error.message}`,
              ),
            );
          } else {
            MZingaLogger.Instance?.error(`[Communications:err] ${err}`);
          }
          throw err;
        }
      },
    ],
  },
  fields: [
    {
      name: "status",
      type: "select",
      options: [
        { label: "Pending", value: "pending" },
        { label: "Processing", value: "processing" },
        { label: "Sent", value: "sent" },
        { label: "Failed", value: "failed" },
      ],
      admin: {
        readOnly: true,
        position: "sidebar",
      },
    },
    {
      name: "subject",
      type: "text",
      required: true,
    },
    {
      name: "tos",
      type: "relationship",
      relationTo: [Slugs.Users],
      required: true,
      hasMany: true,
      validate: (value, { data }) => {
        if (!value && data.sendToAll) {
          return true;
        }
        if (value) {
          return true;
        }
        return "No to(s) or sendToAll have been selected";
      },
      admin: {
        isSortable: true,
      },
      hooks: {
        beforeValidate: [
          async ({ value, data }) => {
            if (data.sendToAll) {
              const promises = [] as Promise<
                PaginatedDocs<Record<string, unknown> & TypeWithID>
              >[];

              const firstSetOfUsers = await payload.find({
                collection: Slugs.Users,
                limit: 100,
              });
              const pages = firstSetOfUsers.totalPages;
              for (let i = 1; i < pages; i++) {
                promises.push(
                  payload.find({
                    collection: Slugs.Users,
                    limit: 100,
                    page: i,
                  }),
                );
              }
              const allDocs = [firstSetOfUsers]
                .concat(await Promise.all(promises))
                .map((p) => p.docs)
                .flat()
                .map((d) => {
                  return { relationTo: Slugs.Users, value: d.id };
                });
              value = allDocs;
            }
            return value;
          },
        ],
      },
    },
    {
      name: "sendToAll",
      type: "checkbox",
      label: "Send to all users?",
    },
    {
      name: "ccs",
      type: "relationship",
      relationTo: [Slugs.Users],
      required: false,
      hasMany: true,
      admin: {
        isSortable: true,
      },
    },
    {
      name: "bccs",
      type: "relationship",
      relationTo: [Slugs.Users],
      required: false,
      hasMany: true,
      admin: {
        isSortable: true,
      },
    },
    {
      name: "body",
      type: "richText",
      required: true,
    },
  ],
};

export default Communications;