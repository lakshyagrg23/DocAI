/**
 * Interface language (English / Hindi). No library: the English sentence is the key, so components keep reading naturally and any
 * string without a Hindi entry simply stays English. `{name}` placeholders are filled from `vars`.
 *
 * The language lives in a module variable (set by `I18nProvider`, which remounts the tree when it changes) so plain helpers
 * such as `verifiedSummary()` can call `t()` without threading a language argument everywhere.
 * Document text, quotes and verified claims are never run through this: claims arrive from the server already translated
 * (`text_local`), quotes stay in the source language.
 */
export type Lang = 'en' | 'hi'

let current: Lang = 'en'
export const getLang = (): Lang => current
export const setLangValue = (l: Lang) => { current = l }

const HI: Record<string, string> = {
  // answer card
  'Answer': 'उत्तर',
  'Answer found': 'उत्तर मिला',
  'Partly answered': 'आंशिक उत्तर',
  'Documents disagree': 'दस्तावेज़ों में मतभेद',
  'No proof found': 'कोई प्रमाण नहीं मिला',
  'Every statement below was checked against your documents.': 'नीचे लिखा हर कथन आपके दस्तावेज़ों से जाँचा गया है।',
  'Some parts are answered; the rest could not be proven.': 'कुछ हिस्सों का उत्तर मिला; बाकी साबित नहीं हो सके।',
  'Your documents give different answers. Both are shown.': 'आपके दस्तावेज़ अलग-अलग उत्तर देते हैं। दोनों दिखाए गए हैं।',
  "I couldn't find proof for this in your documents.": 'मुझे आपके दस्तावेज़ों में इसका प्रमाण नहीं मिला।',
  "Rather than guess, I'm leaving it unanswered. You can rephrase the question or upload the document that covers it.":
    'अंदाज़ा लगाने के बजाय मैं इसे अनुत्तरित छोड़ रहा हूँ। आप प्रश्न बदलकर पूछ सकते हैं या संबंधित दस्तावेज़ अपलोड कर सकते हैं।',
  'the rules that apply today': 'आज लागू नियम',
  'the rules as they applied on {date}': '{date} को लागू नियम',
  'Using {what}': '{what} के आधार पर',
  'Also found': 'यह भी मिला',
  'Sources ({n})': 'स्रोत ({n})',
  'How we checked': 'हमने कैसे जाँचा',
  'Copy the answer as text': 'उत्तर को टेक्स्ट के रूप में कॉपी करें',
  'Copied': 'कॉपी हो गया',
  'Copy answer': 'उत्तर कॉपी करें',
  'No statements were produced': 'कोई कथन तैयार नहीं हुआ',
  'The statement was checked against the documents': 'कथन को दस्तावेज़ों से जाँचा गया',
  'All {n} statements were checked against the documents': 'सभी {n} कथनों को दस्तावेज़ों से जाँचा गया',
  '{passed} of {drafted} statements were verified; {left} left out': '{drafted} में से {passed} कथन सत्यापित हुए; {left} छोड़ दिए गए',
  // blocks
  'Your documents give different answers about the {subject}.': 'आपके दस्तावेज़ {subject} के बारे में अलग-अलग उत्तर देते हैं।',
  'Here is what each document says. Nothing was guessed or averaged.': 'हर दस्तावेज़ में यह लिखा है। कुछ भी अंदाज़े से या औसत निकालकर नहीं लिखा गया।',
  'Document': 'दस्तावेज़',
  'What it says': 'इसमें क्या लिखा है',
  'page {n}': 'पृष्ठ {n}',
  'View source': 'स्रोत देखें',
  'How this rule changed': 'यह नियम कैसे बदला',
  'Showing {what}': '{what} के लिए',
  'today': 'आज',
  'Calculation': 'गणना',
  'from your question': 'आपके प्रश्न से',
  'What I was looking for': 'मैं क्या खोज रहा था',
  "What I couldn't find": 'जो मुझे नहीं मिला',
  'This rule was removed.': 'यह नियम हटा दिया गया था।',
  'Applies today': 'आज लागू',
  'Replaced': 'बदला गया',
  'Not yet in effect': 'अभी लागू नहीं',
  'Removed': 'हटाया गया',
  'Applied on {date}': '{date} को लागू था',
  'Original wording': 'मूल शब्दावली',
  'Replaced by': 'इससे बदला गया',
  'Added by': 'इससे जोड़ा गया',
  'Removed by': 'इससे हटाया गया',
  'Until {date}': '{date} तक',
  'From {date}': '{date} से',
  'no charge': 'कोई शुल्क नहीं',
  'at most {v}': 'अधिकतम {v}',
  'at least {v}': 'कम से कम {v}',
  'per instalment': 'प्रति किस्त', 'per instance': 'प्रति बार', 'per month': 'प्रति माह', 'per year': 'प्रति वर्ष',
  'Strong': 'मज़बूत', 'Adequate': 'पर्याप्त', 'Weak': 'कमज़ोर', 'Not scored': 'अंक नहीं',
  'It could not be verified.': 'इसे सत्यापित नहीं किया जा सका।',
  'The documents disagree on this.': 'इस पर दस्तावेज़ों में मतभेद है।',
  'Points at text that was actually retrieved': 'वास्तव में खोजे गए पाठ की ओर इशारा करता है',
  'Every number and date matches the source text': 'हर संख्या और तारीख स्रोत पाठ से मेल खाती है',
  'Quotations match the source word for word': 'उद्धरण स्रोत से शब्दशः मेल खाते हैं',
  'The rule applies on the chosen date': 'चुनी गई तारीख पर यह नियम लागू है',
  // progress
  'Understanding your question': 'आपका प्रश्न समझा जा रहा है',
  'Finding relevant passages': 'संबंधित अंश खोजे जा रहे हैं',
  'Writing the answer': 'उत्तर लिखा जा रहा है',
  'Checking every statement against the documents': 'हर कथन को दस्तावेज़ों से जाँचा जा रहा है',
  'Comparing documents for disagreements': 'दस्तावेज़ों में मतभेद खोजे जा रहे हैं',
  'Waiting for the model…': 'मॉडल की प्रतीक्षा…',
  'Working on your answer…': 'आपका उत्तर तैयार हो रहा है…',
  'Answers appear only after every statement has been checked, so this can take up to a minute.':
    'उत्तर तभी दिखता है जब हर कथन जाँच लिया जाए, इसलिए इसमें एक मिनट तक लग सकता है।',
  // composer / chat page
  'Ask a question about your documents…': 'अपने दस्तावेज़ों के बारे में प्रश्न पूछें…',
  'Your question': 'आपका प्रश्न',
  'Send question': 'प्रश्न भेजें',
  'Rules as of today': 'आज के नियम',
  'Rules as of {date}': '{date} के नियम',
  'Answers use the rules as they applied on this date. Change it to see an older or future rule.':
    'उत्तर इस तारीख को लागू नियमों पर आधारित होते हैं। पुराना या भविष्य का नियम देखने के लिए इसे बदलें।',
  'Every statement is checked against your documents before it is shown. Press Enter to send.':
    'हर कथन दिखाने से पहले आपके दस्तावेज़ों से जाँचा जाता है। भेजने के लिए Enter दबाएँ।',
  'The model is warming up or offline, so answers may fail for a few minutes. Your documents are still available.':
    'मॉडल शुरू हो रहा है या बंद है, इसलिए कुछ मिनट उत्तर विफल हो सकते हैं। आपके दस्तावेज़ उपलब्ध हैं।',
  'Add documents to get started': 'शुरू करने के लिए दस्तावेज़ जोड़ें',
  'What would you like to verify?': 'आप क्या सत्यापित करना चाहेंगे?',
  'Add documents': 'दस्तावेज़ जोड़ें',
  'New chat': 'नई चैट',
  'Export': 'निर्यात',
  'Open sidebar': 'साइडबार खोलें',
  'Something went wrong. Please try again.': 'कुछ गलत हो गया। कृपया फिर से प्रयास करें।',
  // sidebar / shell
  'Language': 'भाषा',
  'Switch to Hindi': 'हिन्दी में बदलें',
  'Switch to English': 'Switch to English',
  'Library': 'दस्तावेज़', 'Documents': 'दस्तावेज़', 'Conflicts': 'मतभेद', 'Amendments': 'संशोधन',
  'Today': 'आज', 'Yesterday': 'कल', 'Previous 7 days': 'पिछले 7 दिन', 'Older': 'पुराने',
}

const MONTHS_HI = ['जन', 'फ़र', 'मार्च', 'अप्रैल', 'मई', 'जून', 'जुल', 'अग', 'सित', 'अक्तू', 'नव', 'दिस']
export const monthName = (i: number, en: string[]): string => (current === 'hi' ? MONTHS_HI[i] : en[i])

/** Translate an English UI string; unknown strings stay English. `{name}` placeholders come from `vars`. */
export function t(en: string, vars?: Record<string, string | number>): string {
  const base = (current === 'hi' && HI[en]) || en
  return vars ? base.replace(/\{(\w+)\}/g, (_, k: string) => String(vars[k] ?? `{${k}}`)) : base
}
